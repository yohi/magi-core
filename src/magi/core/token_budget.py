"""トークン予算管理と要約ロジック."""

from dataclasses import dataclass
from typing import List

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

    def __init__(self, max_tokens: int, tokens_per_char: float = 0.5) -> None:
        """コンストラクタ.

        Args:
            max_tokens: 許容する最大トークン数。
            tokens_per_char: 文字あたりの推定トークン数。
        """
        self.max_tokens = max_tokens
        self.tokens_per_char = tokens_per_char

    def estimate_tokens(self, text: str) -> int:
        """文字列のトークン数を推定する."""
        return int(len(text) * self.tokens_per_char)

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

        picked: List[str] = []
        token_count = 0
        for _, _, segment in scored_segments:
            segment_tokens = self.estimate_tokens(segment)
            if token_count + segment_tokens > self.max_tokens:
                continue
            picked.append(segment)
            token_count += segment_tokens

        if not picked:
            # すべて長すぎる場合は先頭セグメントを使用する
            return segments[0]

        return "\n\n".join(picked)

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
        if any(
            marker in segment
            for marker in ("##", "【", "###", "---", "反論", "Thinking", "Debate")
        ):
            score += 2
        if len(segment) < 120:
            score += 1
        return score
