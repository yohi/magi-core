"""会話履歴管理モジュール

Requirements: 7.1, 7.2, 7.3, 7.4
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from magi.models import ConsensusPhase, PersonaType


@dataclass
class ConversationEntry:
    """会話履歴のエントリ

    Attributes:
        phase: 合議プロセスのフェーズ
        persona_type: ペルソナタイプ
        content: 会話内容
        timestamp: タイムスタンプ（デフォルトは現在時刻）
    """
    phase: ConsensusPhase
    persona_type: PersonaType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


class ContextManager:
    """会話履歴の管理

    会話履歴を管理し、フェーズごとのコンテキスト取得、
    トークン制限に基づく要約/削除機能を提供する。

    Attributes:
        max_tokens: 最大トークン数（デフォルト: 100000）
        history: 会話履歴のリスト
    """

    # トークン推定の係数（1文字あたりのトークン数の概算）
    # 英語: 約0.25、日本語: 約0.5-1.0
    _TOKENS_PER_CHAR = 0.5

    # 制限に近いと判定する閾値（max_tokensの80%）
    _NEAR_LIMIT_THRESHOLD = 0.8

    def __init__(self, max_tokens: int = 100000):
        """ContextManagerの初期化

        Args:
            max_tokens: 最大トークン数
        """
        self.max_tokens = max_tokens
        self.history: List[ConversationEntry] = []

    def add_entry(self, entry: ConversationEntry) -> None:
        """履歴にエントリを追加する

        Requirements 7.1: 各フェーズが完了するとエージェントの出力を会話履歴に追加

        Args:
            entry: 追加する会話エントリ
        """
        self.history.append(entry)

    def get_context_for_phase(self, phase: ConsensusPhase) -> str:
        """フェーズに必要なコンテキストを取得する

        Requirements 7.2: 新しいフェーズが開始されると必要な履歴情報を
        各エージェントのコンテキストに含める

        Args:
            phase: 対象フェーズ

        Returns:
            フェーズに適したコンテキスト文字列
        """
        if phase == ConsensusPhase.THINKING:
            # Thinking Phaseでは他のエージェントの出力を含めない
            return ""

        if phase == ConsensusPhase.DEBATE:
            # Debate Phaseでは全エージェントのThinking結果を含める
            return self._build_thinking_context()

        if phase == ConsensusPhase.VOTING:
            # Voting Phaseでは全履歴を含める
            return self._build_full_context()

        return ""

    def _build_thinking_context(self) -> str:
        """Thinking Phaseの結果からコンテキストを構築する

        Returns:
            Thinking Phaseのコンテキスト文字列
        """
        thinking_entries = self.get_entries_by_phase(ConsensusPhase.THINKING)
        if not thinking_entries:
            return ""

        lines = ["## 各エージェントの思考結果\n"]
        for entry in thinking_entries:
            persona_name = self._get_persona_display_name(entry.persona_type)
            lines.append(f"### {persona_name}")
            lines.append(entry.content)
            lines.append("")

        return "\n".join(lines)

    def _build_full_context(self) -> str:
        """全履歴からコンテキストを構築する

        Returns:
            全履歴のコンテキスト文字列
        """
        if not self.history:
            return ""

        lines = []
        current_phase: Optional[ConsensusPhase] = None

        for entry in self.history:
            if entry.phase != current_phase:
                current_phase = entry.phase
                phase_name = self._get_phase_display_name(entry.phase)
                lines.append(f"## {phase_name}\n")

            persona_name = self._get_persona_display_name(entry.persona_type)
            lines.append(f"### {persona_name}")
            lines.append(entry.content)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _get_persona_display_name(persona_type: PersonaType) -> str:
        """ペルソナの表示名を取得する

        Args:
            persona_type: ペルソナタイプ

        Returns:
            表示名
        """
        display_names = {
            PersonaType.MELCHIOR: "MELCHIOR-1（論理・科学）",
            PersonaType.BALTHASAR: "BALTHASAR-2（倫理・保護）",
            PersonaType.CASPER: "CASPER-3（欲望・実利）",
        }
        return display_names.get(persona_type, persona_type.value)

    @staticmethod
    def _get_phase_display_name(phase: ConsensusPhase) -> str:
        """フェーズの表示名を取得する

        Args:
            phase: フェーズ

        Returns:
            表示名
        """
        display_names = {
            ConsensusPhase.THINKING: "Thinking Phase（独立思考）",
            ConsensusPhase.DEBATE: "Debate Phase（議論）",
            ConsensusPhase.VOTING: "Voting Phase（投票）",
            ConsensusPhase.COMPLETED: "Completed（完了）",
        }
        return display_names.get(phase, phase.value)

    def export(self) -> Dict:
        """履歴を構造化形式でエクスポートする

        Requirements 7.3: 合議プロセスが完了すると全体の会話履歴を
        構造化された形式で出力可能にする

        Returns:
            履歴の辞書形式
        """
        entries_data = []
        for entry in self.history:
            entries_data.append({
                "phase": entry.phase.value,
                "persona_type": entry.persona_type.value,
                "content": entry.content,
                "timestamp": entry.timestamp.isoformat(),
            })

        return {
            "entries": entries_data,
            "total_entries": len(entries_data),
        }

    def get_entries_by_phase(self, phase: ConsensusPhase) -> List[ConversationEntry]:
        """指定フェーズのエントリを取得する

        Args:
            phase: 対象フェーズ

        Returns:
            該当フェーズのエントリリスト
        """
        return [entry for entry in self.history if entry.phase == phase]

    def get_entries_by_persona(self, persona_type: PersonaType) -> List[ConversationEntry]:
        """指定ペルソナのエントリを取得する

        Args:
            persona_type: 対象ペルソナタイプ

        Returns:
            該当ペルソナのエントリリスト
        """
        return [entry for entry in self.history if entry.persona_type == persona_type]

    def clear(self) -> None:
        """履歴をクリアする"""
        self.history.clear()

    def estimate_tokens(self) -> int:
        """現在の履歴のトークン数を推定する

        概算として、文字数にトークン係数を掛けて計算する。
        実際のトークン数は使用するモデルやエンコーディングによって異なる。

        Returns:
            推定トークン数
        """
        total_chars = sum(len(entry.content) for entry in self.history)
        return int(total_chars * self._TOKENS_PER_CHAR)

    @property
    def current_token_count(self) -> int:
        """現在のトークン数（推定値）

        Returns:
            推定トークン数
        """
        return self.estimate_tokens()

    def is_near_limit(self) -> bool:
        """トークン制限に近づいているかを判定する

        Returns:
            制限の80%を超えている場合True
        """
        return self.current_token_count >= self.max_tokens * self._NEAR_LIMIT_THRESHOLD

    def summarize_if_needed(self) -> None:
        """トークン制限に近づいた場合に履歴を要約または削除する

        Requirements 7.4: 会話履歴のサイズがトークン制限に近づくと
        古い履歴を要約または削除して制限内に収める

        現在の実装では、最も古いエントリから削除する単純な方式を採用。
        将来的にはLLMを使用した要約機能に拡張可能。
        """
        while self.current_token_count > self.max_tokens and len(self.history) > 0:
            # 最も古いエントリを削除
            self.history.pop(0)

    def get_summary(self) -> str:
        """履歴の要約を取得する

        Returns:
            履歴の要約文字列
        """
        if not self.history:
            return "履歴なし"

        # フェーズごとのエントリ数をカウント
        phase_counts: Dict[ConsensusPhase, int] = {}
        persona_counts: Dict[PersonaType, int] = {}

        for entry in self.history:
            phase_counts[entry.phase] = phase_counts.get(entry.phase, 0) + 1
            persona_counts[entry.persona_type] = persona_counts.get(entry.persona_type, 0) + 1

        lines = ["## 会話履歴サマリー\n"]

        lines.append("### フェーズ別エントリ数")
        for phase, count in phase_counts.items():
            phase_name = self._get_phase_display_name(phase)
            lines.append(f"- {phase_name}: {count}")
        lines.append("")

        lines.append("### ペルソナ別エントリ数")
        for persona, count in persona_counts.items():
            persona_name = self._get_persona_display_name(persona)
            lines.append(f"- {persona_name}: {count}")
        lines.append("")

        lines.append(f"### 統計")
        lines.append(f"- 総エントリ数: {len(self.history)}")
        lines.append(f"- 推定トークン数: {self.current_token_count}")
        lines.append(f"- 最大トークン数: {self.max_tokens}")

        return "\n".join(lines)
