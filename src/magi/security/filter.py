"""セキュリティフィルタ

ユーザー入力のサニタイズと禁止パターン検出を行う。
"""

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import List
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


@dataclass
class SanitizedText:
    """サニタイズ結果"""

    safe: str
    markers_applied: bool
    removed_patterns: List[str]
    matched_rules: List[str]
    blocked: bool


@dataclass
class DetectionResult:
    """検知結果"""

    blocked: bool
    matched_rules: List[str]


class SecurityFilter:
    """入力サニタイズと検知ロジック"""

    def sanitize_prompt(self, raw: str) -> SanitizedText:
        """ユーザー入力をサニタイズし、禁止パターンを検知する。

        removed_patterns は現状未実装のため常に空リストとなる。
        """
        text = raw or ""
        self._validate_length(text)
        matched_rules = self._detect_patterns(text)
        blocked = any(rule != "whitelist_deviation" for rule in matched_rules)

        normalized = self._normalize(text)
        escaped = self._escape_control_sequences(normalized)
        with_markers = f"<<USER_INPUT>>{escaped}<<END_USER_INPUT>>"

        return SanitizedText(
            safe=with_markers,
            markers_applied=True,
            removed_patterns=[],
            matched_rules=matched_rules,
            blocked=blocked,
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
