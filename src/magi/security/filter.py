"""セキュリティフィルタ

ユーザー入力のサニタイズと禁止パターン検出を行う。
"""

import hashlib
import html
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import unquote

from magi.errors import MagiError, MagiException

# ホワイトリストと禁止パターン
WHITELIST_PATTERN = re.compile(r"^[A-Za-z0-9_.\s,:;\"'@/\(\)\[\]-]+$")
FORBIDDEN_PATTERNS = {
    "blacklist_ignore_previous": re.compile(r"(?i)\bignore\s+all\s+previous\b"),
    "blacklist_system_prompt": re.compile(r"(?i)\b(system|sys)\s*prompt\b"),
    "blacklist_script_tag": re.compile(r"(?s)<\s*script.*?>.*?<\s*/\s*script\s*>"),
    "blacklist_private_key": re.compile(r"(?i)---BEGIN[^\n]{0,40}PRIVATE\s+KEY---"),
    "blacklist_encoded_script_tag": re.compile(
        r"(?is)(?:&#0*60;|&lt;|%3[cC]|\\x3[cC])\s*script.*?(?:&#0*62;|&gt;|%3[eE]|\\x3[eE])"
    ),
    "blacklist_encoded_html_tag": re.compile(
        r"(?is)(?:%3[cC]|\\x3[cC]|&#0*60;|&lt;)[^>]{0,40}(script|img|iframe|form)[^>]{0,200}(?:%3[eE]|\\x3[eE]|&#0*62;|&gt;)"
    ),
    "blacklist_base64_pem_or_tag": re.compile(
        r"(?i)\b(?:LS0tLS1CRUdJTi|PHNjcmlwdC|PD9|UEVN)[A-Za-z0-9+/]{12,}={0,2}\b"
    ),
    "blacklist_hex_tag_blob": re.compile(r"(?i)\b(?:3c73|3c2f73|3c3f)[0-9a-f]{12,}\b"),
    "blacklist_persona_injection": re.compile(
        r"(?i)\b(act\s+as|assume\s+the\s+role|role\s*play|you\s+are\s+now|DAN|developer\s+mode)\b"
    ),
    "blacklist_multi_step_chaining": re.compile(
        r"(?i)\b(ignore\s+all\s+previous|disregard\s+earlier|switch\s+role|reset\s+instructions)\b"
    ),
}
INVISIBLE_PATTERN = re.compile(r"[\u200d\u200c\uFEFF]")
MAX_INPUT_LENGTH = 10_000
MASK_TOKEN = "********"
MASKED_SNIPPET_MAX_CP = 32
_AUDIT_WARNING_EMITTED = False
_AUDIT_LOGGER = logging.getLogger("magi.audit.security")


@dataclass
class SanitizedText:
    """サニタイズ結果"""

    safe: str
    markers_applied: bool
    removed_patterns: List[Dict[str, Any]]
    matched_rules: List[str]
    blocked: bool
    removed_patterns_present: bool


@dataclass
class DetectionResult:
    """検知結果"""

    blocked: bool
    matched_rules: List[str]


class SecurityFilter:
    """入力サニタイズと検知ロジック"""

    def __init__(
        self,
        *,
        mask_hashing: bool = False,
        audit_logger: Optional[logging.Logger] = None,
    ) -> None:
        self.mask_hashing = mask_hashing
        self.audit_logger = audit_logger or _AUDIT_LOGGER

    def sanitize_prompt(self, raw: str) -> SanitizedText:
        """ユーザー入力をサニタイズし、禁止パターンを検知する。

        removed_patterns は現状未実装のため常に空リストとなる。
        """
        text = raw or ""
        self._validate_length(text)
        matched_rules = self._detect_patterns(text)
        blocked = any(rule != "whitelist_deviation" for rule in matched_rules)
        removed_patterns, removed_present = self._build_removed_patterns(text)
        self._emit_audit_log(removed_patterns, removed_present)

        normalized = self._normalize(text)
        escaped = self._escape_control_sequences(normalized)
        with_markers = f"<<USER_INPUT>>{escaped}<<END_USER_INPUT>>"

        return SanitizedText(
            safe=with_markers,
            markers_applied=True,
            removed_patterns=removed_patterns,
            matched_rules=matched_rules,
            blocked=blocked,
            removed_patterns_present=removed_present,
        )

    def detect_abuse(self, raw: str) -> DetectionResult:
        """禁止パターン検知のみを行う"""
        text = raw or ""
        self._validate_length(text)
        matched = self._detect_patterns(text)
        # ホワイトリスト逸脱のみの場合はブロックしない
        non_whitelist_matches = [rule for rule in matched if rule != "whitelist_deviation"]
        blocked = bool(non_whitelist_matches)
        return DetectionResult(blocked=blocked, matched_rules=matched)

    def sanitize_for_logging(self, text: str) -> str:
        """ログ用にサニタイズする(機微情報をエスケープ)"""
        normalized = self._normalize(text or "")
        return self._escape_control_sequences(normalized)

    def _normalize(self, text: str) -> str:
        """改行・不可視文字を正規化"""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\0", "\\u0000")
        normalized = INVISIBLE_PATTERN.sub("", normalized)
        return normalized

    def _escape_control_sequences(self, text: str) -> str:
        """テンプレート境界や制御記号をエスケープ"""
        replacements = {
            "{{": "\\{{",
            "}}": "\\}}",
            "<<": "\\<<",
            ">>": "\\>>",
            "[[": "\\[[",
            "]]": "\\]]",
        }
        escaped = text
        for needle, repl in replacements.items():
            escaped = escaped.replace(needle, repl)
        return escaped

    def _detect_patterns(self, text: str) -> List[str]:
        """禁止パターンとホワイトリスト逸脱を検知"""
        matched: List[str] = []
        text_to_check = self._canonicalize_for_detection(text)
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text_to_check):
                matched.append(name)

        if text_to_check and not WHITELIST_PATTERN.fullmatch(text_to_check):
            matched.append("whitelist_deviation")

        return matched

    def _canonicalize_for_detection(self, text: str) -> str:
        """禁止パターン検知向けの正規化とデコード"""
        if not isinstance(text, str):
            return ""
        # 不可視文字除去と改行統一
        cleaned = INVISIBLE_PATTERN.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
        cleaned = cleaned.replace("\0", "\\u0000")
        # HTMLエンティティ → パーセントエンコード解除 → NFKC正規化
        unescaped = html.unescape(cleaned)
        percent_decoded = unquote(unescaped)
        normalized = unicodedata.normalize("NFKC", percent_decoded)
        # NFKC後に残る不可視文字を再除去
        return INVISIBLE_PATTERN.sub("", normalized)

    def _validate_length(self, text: str) -> None:
        """入力長が上限を超える場合に例外を送出"""
        length = len(text or "")
        if length > MAX_INPUT_LENGTH:
            raise MagiException(
                MagiError(
                    code="SECURITY_INPUT_TOO_LONG",
                    message=(
                        f"入力が長すぎます（最大 {MAX_INPUT_LENGTH} 文字, 受信 {length} 文字）。"
                    ),
                    details={"max_length": MAX_INPUT_LENGTH, "length": length},
                    recoverable=False,
                )
            )

    def _mask_fragment(self, fragment: str) -> Tuple[str, int]:
        """機微断片をマスクし、元の長さを返す"""
        original_length = len(fragment or "")
        if self.mask_hashing:
            digest = hashlib.sha256((fragment or "").encode("utf-8")).hexdigest()[:8]
            masked = f"masked:sha256:{digest}"
        else:
            masked = MASK_TOKEN
        if len(masked) < MASKED_SNIPPET_MAX_CP:
            masked = masked.ljust(MASKED_SNIPPET_MAX_CP, "*")
        else:
            masked = masked[:MASKED_SNIPPET_MAX_CP]
        return masked, original_length

    def _build_removed_patterns(self, raw_text: str) -> Tuple[List[Dict[str, Any]], bool]:
        """検知結果を元に removed_patterns 情報を組み立てる"""
        entries: List[Dict[str, Any]] = []
        canonical = self._canonicalize_for_detection(raw_text or "")
        removed_present = False

        for pattern_id, pattern in FORBIDDEN_PATTERNS.items():
            matches = list(pattern.finditer(canonical))
            if not matches:
                continue
            removed_present = True
            masked_snippet, original_length = self._mask_fragment(matches[0].group(0))
            entries.append(
                {
                    "pattern_id": pattern_id,
                    "count": len(matches),
                    "masked_snippet": masked_snippet,
                    "original_length": original_length,
                }
            )

        if not removed_present:
            masked_snippet, _ = self._mask_fragment("")
            entries.append(
                {
                    "pattern_id": "none",
                    "count": 0,
                    "masked_snippet": masked_snippet,
                    "original_length": 0,
                }
            )

        return entries, removed_present

    def _emit_audit_log(self, entries: List[Dict[str, Any]], present: bool) -> None:
        """監査ログへマスク済み断片を出力し、未設定時は一度だけ警告"""
        logger = self.audit_logger
        if not self._audit_has_destination(logger):
            self._warn_audit_once()

        for entry in entries:
            try:
                logger.info(
                    "security.filter.removed_patterns",
                    extra={
                        "pattern_id": entry.get("pattern_id"),
                        "count": entry.get("count", 0),
                        "masked_snippet": entry.get("masked_snippet"),
                        "original_length": entry.get("original_length", 0),
                        "removed_patterns_present": present,
                        "mask_hashing": self.mask_hashing,
                    },
                )
            except Exception:  # pragma: no cover - ログ失敗は処理継続
                logger.debug("audit log failed for removed_patterns", exc_info=True)

    @staticmethod
    def _audit_has_destination(logger: logging.Logger) -> bool:
        """監査ログの出力先有無を判定する"""
        if logger.handlers:
            return True
        return logger.hasHandlers()

    def _warn_audit_once(self) -> None:
        """監査ログ未設定時の警告（プロセスで1回だけ）"""
        global _AUDIT_WARNING_EMITTED
        if _AUDIT_WARNING_EMITTED:
            return
        _AUDIT_WARNING_EMITTED = True
        print(
            "警告: 監査ログが無効です。ハンドラを設定して SecurityFilter の監査ログを記録してください。",
            file=sys.stderr,
        )
