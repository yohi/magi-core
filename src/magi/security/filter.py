"""セキュリティフィルタ

ユーザー入力のサニタイズと禁止パターン検出を行う。
"""

import re
from dataclasses import dataclass
from typing import List

# ホワイトリストと禁止パターン
WHITELIST_PATTERN = re.compile(r"^[A-Za-z0-9_\-.\s,:;\"'@/\(\)\[\]]+$")
FORBIDDEN_PATTERNS = {
    "blacklist_ignore_previous": re.compile(r"(?i)\bignore\s+all\s+previous\b"),
    "blacklist_system_prompt": re.compile(r"(?i)\b(system|sys)\s*prompt\b"),
    "blacklist_script_tag": re.compile(r"(?s)<\s*script.*?>.*?<\s*/\s*script\s*>"),
    "blacklist_private_key": re.compile(r"(?i)---BEGIN[^\n]{0,40}PRIVATE\s+KEY---"),
}
INVISIBLE_PATTERN = re.compile(r"[\u200d\u200c\uFEFF]")


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
        """ユーザー入力をサニタイズし、禁止パターンを検知する"""
        text = raw or ""
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
        matched = self._detect_patterns(raw or "")
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
        text_to_check = text if isinstance(text, str) else ""
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text_to_check):
                matched.append(name)

        if text_to_check and not WHITELIST_PATTERN.fullmatch(text_to_check):
            matched.append("whitelist_deviation")

        return matched
