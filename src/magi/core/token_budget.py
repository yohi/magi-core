"""トークン予算管理と要約ロジック."""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from magi.models import ConsensusPhase


@dataclass
class ReductionLog:
    """削減ログのエントリ."""

    phase: str
    reason: str
    before_tokens: int
    after_tokens: int


@dataclass
class BudgetResult:
    """予算適用結果."""

    context: str
    summary_applied: bool
    reduced_tokens: int
    logs: List[ReductionLog]


class TokenBudgetManager:
    """トークン予算の強制と要約/圧縮を行う."""

    _LANGUAGE_TOKEN_RATES = {
        "ja": 0.72,  # 実測レンジ: おおよそ0.67〜0.77
        "en": 0.45,  # 実測レンジ: おおよそ0.35〜0.50
    }

    def __init__(
        self,
        max_tokens: int,
        tokens_per_char: Optional[float] = None,
        language: Optional[str] = None,
    ) -> None:
        """コンストラクタ.

        日本語は英語より1文字あたりのトークン数が大きく、実測レンジは
        おおよそ日本語0.67〜0.77、英語0.35〜0.50程度。この差を考慮するため、
        言語別ヒューリスティックか明示的なトークン率を選べるようにする。

        Args:
            max_tokens: 許容する最大トークン数。
            tokens_per_char: 文字あたりの推定トークン数。指定があれば最優先。
            language: 言語コード（例: "ja", "en"）。tokens_per_char未指定時に使用。
        """
        if tokens_per_char is not None and tokens_per_char <= 0:
            raise ValueError("tokens_per_char must be > 0")
        if max_tokens < 0:
            raise ValueError("max_tokens must be >= 0")
        self.max_tokens = max_tokens
        self.language = language.lower() if language else None
        self.tokens_per_char = (
            tokens_per_char
            if tokens_per_char is not None
            else self._resolve_tokens_per_char(self.language)
        )

    def estimate_tokens(self, text: str, language: Optional[str] = None) -> int:
        """文字列のトークン数を推定する."""
        rate = (
            self._resolve_tokens_per_char(language)
            if language is not None
            else self.tokens_per_char
        )
        return int(math.ceil(len(text) * rate))

    def _resolve_tokens_per_char(self, language: Optional[str]) -> float:
        """言語ごとの推定トークン率を返す."""
        if language:
            lang = language.lower()
            if lang in self._LANGUAGE_TOKEN_RATES:
                return self._LANGUAGE_TOKEN_RATES[lang]
        return 0.5

    def enforce(self, context: str, phase: ConsensusPhase) -> BudgetResult:
        """コンテキストに予算を適用し、必要なら要約/圧縮する."""
        before = self.estimate_tokens(context)
        logs: List[ReductionLog] = []

        if before <= self.max_tokens:
            return BudgetResult(
                context=context,
                summary_applied=False,
                reduced_tokens=0,
                logs=logs,
            )

        reduced = self._compress(context)
        after = self.estimate_tokens(reduced)
        reason = "token_budget_exceeded_summary"

        if after > self.max_tokens:
            reduced = self._trim_to_budget(reduced)
            after = self.estimate_tokens(reduced)
            reason = "token_budget_exceeded_trimmed"

        logs.append(
            ReductionLog(
                phase=phase.value,
                reason=reason,
                before_tokens=before,
                after_tokens=after,
            )
        )

        return BudgetResult(
            context=reduced,
            summary_applied=True,
            reduced_tokens=max(before - after, 0),
            logs=logs,
        )

    def _compress(self, context: str) -> str:
        """簡易な重要度スコアでセグメントを優先度順に圧縮する."""
        segments = context.split("\n\n")
        scored_segments = []
        for idx, segment in enumerate(segments):
            score = self._score_segment(segment)
            scored_segments.append((score, idx, segment))

        scored_segments.sort(key=lambda item: (-item[0], item[1]))

        picked: List[Tuple[int, str]] = []
        token_count = 0
        for _, idx, segment in scored_segments:
            segment_tokens = self.estimate_tokens(segment)
            if token_count + segment_tokens > self.max_tokens:
                continue
            picked.append((idx, segment))
            token_count += segment_tokens

        if not picked:
            # すべて長すぎる場合は先頭セグメントを予算に合わせて切り詰めて使用する
            return self._trim_to_budget(segments[0])

        picked.sort(key=lambda item: item[0])
        return "\n\n".join(segment for _, segment in picked)

    def _trim_to_budget(self, context: str) -> str:
        """最終的に予算に収まるよう安全に切り詰める."""
        max_chars = int(self.max_tokens / self.tokens_per_char)
        if len(context) <= max_chars:
            return context
        return context[:max_chars]

    @staticmethod
    def _score_segment(segment: str) -> int:
        """セグメントの重要度スコアを計算する."""
        score = 1
        heading_markers = ("##", "###")
        priority_markers = ("【", "---", "反論", "Thinking", "Debate")

        # Markdown見出しは他の重要マーカーより強く扱い、後段のまとめを優先する
        if any(marker in segment for marker in heading_markers):
            score += 3
        elif any(marker in segment for marker in priority_markers):
            score += 2
        if len(segment) < 120:
            score += 1
        return score
