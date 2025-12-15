"""トークン予算管理と要約ロジック."""

import math
from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple, runtime_checkable

from magi.models import ConsensusPhase


class TokenBudgetExceeded(Exception):
    """トークン予算を超過したことを示す例外."""

    def __init__(self, estimated_tokens: int, max_tokens: Optional[int] = None):
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens
        message = "トークン予算を超過しました"
        if max_tokens is not None:
            message = f"{message}: estimated={estimated_tokens}, max={max_tokens}"
        super().__init__(message)


@dataclass
class ReductionLog:
    """削減ログのエントリ."""

    phase: str
    reason: str
    before_tokens: int
    after_tokens: int
    retain_ratio: float
    summary_applied: bool
    strategy: str


@dataclass
class BudgetResult:
    """予算適用結果."""

    context: str
    summary_applied: bool
    reduced_tokens: int
    logs: List[ReductionLog]


@runtime_checkable
class TokenBudgetManagerProtocol(Protocol):
    """トークン予算管理の最小インターフェース."""

    def check_budget(self, estimated_tokens: int) -> bool:
        """推定トークン数が予算内かを判定する."""

    def consume(self, actual_tokens: int) -> None:
        """実際に消費したトークン数を記録する."""


class SimpleTokenBudgetManager(TokenBudgetManagerProtocol):
    """推定/実測トークンを追跡する軽量マネージャ."""

    def __init__(self, max_tokens: Optional[int]) -> None:
        if max_tokens is not None and max_tokens < 0:
            raise ValueError("max_tokens must be >= 0")
        self.max_tokens = max_tokens
        self._consumed = 0

    def check_budget(self, estimated_tokens: int) -> bool:
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens must be >= 0")
        if self.max_tokens is None:
            return True
        return self._consumed + estimated_tokens <= self.max_tokens

    def consume(self, actual_tokens: int) -> None:
        if actual_tokens < 0:
            raise ValueError("actual_tokens must be >= 0")
        if self.max_tokens is None:
            return
        self._consumed += actual_tokens

    @property
    def consumed(self) -> int:
        """これまでに記録したトークン消費量."""
        return self._consumed


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

    def check_budget(self, estimated_tokens: int) -> bool:
        """推定トークン数が予算内かを判定する."""
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens must be >= 0")
        return estimated_tokens <= self.max_tokens

    def consume(self, actual_tokens: int) -> None:
        """TokenBudgetManager は累積管理を行わないため記録のみ."""
        if actual_tokens < 0:
            raise ValueError("actual_tokens must be >= 0")

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

        reduced, trimmed_in_compress = self._compress(context)
        after = self.estimate_tokens(reduced)
        summary_used = False
        strategy = "trim_to_budget" if trimmed_in_compress else "priority_only"
        reason = (
            "token_budget_exceeded_trimmed"
            if trimmed_in_compress
            else "token_budget_reduced_priority_only"
        )

        summarized = self._summarize(reduced)
        if summarized != reduced and not trimmed_in_compress:
            summary_used = True
            strategy = "with_summary"
            reason = "token_budget_reduced_with_summary"
            reduced = summarized
            after = self.estimate_tokens(reduced)

        if after > self.max_tokens:
            reduced = self._trim_to_budget(reduced)
            after = self.estimate_tokens(reduced)
            strategy = "trim_to_budget"
            reason = "token_budget_exceeded_trimmed"

        retain_ratio = after / before if before > 0 else 0.0

        logs.append(
            ReductionLog(
                phase=phase.value,
                reason=reason,
                before_tokens=before,
                after_tokens=after,
                retain_ratio=retain_ratio,
                summary_applied=summary_used,
                strategy=strategy,
            )
        )

        return BudgetResult(
            context=reduced,
            summary_applied=True,
            reduced_tokens=max(before - after, 0),
            logs=logs,
        )

    def _compress(self, context: str) -> Tuple[str, bool]:
        """簡易な重要度スコアでセグメントを優先度順に圧縮する.

        Returns:
            圧縮後のコンテキストと、切り詰めを行ったかどうかのフラグ。
        """
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
            return self._trim_to_budget(segments[0]), True

        picked.sort(key=lambda item: item[0])
        return "\n\n".join(segment for _, segment in picked), False

    def _summarize(self, context: str) -> str:
        """重要度選択後のセグメントを予算に合わせて要約する."""
        segments = [segment.strip() for segment in context.split("\n\n") if segment.strip()]
        if not segments:
            return context

        max_chars = int(self.max_tokens / self.tokens_per_char)
        per_segment_limit = max(max_chars // len(segments), 1)

        summarized_segments = []
        for segment in segments:
            if len(segment) <= per_segment_limit:
                summarized_segments.append(segment)
            else:
                summarized_segments.append(segment[:per_segment_limit])

        return "\n\n".join(summarized_segments)

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
