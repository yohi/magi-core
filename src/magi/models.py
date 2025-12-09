"""
共通データモデル

MAGIシステム全体で使用されるデータ構造を定義
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Vote(Enum):
    """エージェントの投票結果"""
    APPROVE = "approve"
    DENY = "deny"
    CONDITIONAL = "conditional"


class Decision(Enum):
    """合議の最終判定"""
    APPROVED = "approved"
    DENIED = "denied"
    CONDITIONAL = "conditional"


class PersonaType(Enum):
    """3賢者のペルソナタイプ"""
    MELCHIOR = "melchior"
    BALTHASAR = "balthasar"
    CASPER = "casper"


class ConsensusPhase(Enum):
    """合議プロセスのフェーズ"""
    THINKING = "thinking"
    DEBATE = "debate"
    VOTING = "voting"
    COMPLETED = "completed"


@dataclass
class VotingTally:
    """投票結果の集計

    Attributes:
        approve_count: APPROVE票の数
        deny_count: DENY票の数
        conditional_count: CONDITIONAL票の数
    """
    approve_count: int
    deny_count: int
    conditional_count: int

    def get_decision(self, threshold: str) -> Decision:
        """閾値に基づいて最終判定を決定

        Args:
            threshold: 判定閾値（"majority" または "unanimous"）

        Returns:
            Decision: 最終判定結果

        Raises:
            ValueError: thresholdが"unanimous"または"majority"以外の場合
        """
        total_votes = self.approve_count + self.deny_count + self.conditional_count

        if threshold == "unanimous":
            if total_votes > 0 and self.approve_count == total_votes:
                return Decision.APPROVED
            elif self.deny_count >= 1:
                return Decision.DENIED
            else:
                return Decision.CONDITIONAL
        elif threshold == "majority":
            if total_votes == 0:
                return Decision.CONDITIONAL

            majority_threshold = total_votes // 2 + 1

            if self.approve_count >= majority_threshold:
                return Decision.APPROVED
            elif self.deny_count >= majority_threshold:
                return Decision.DENIED
            else:
                return Decision.CONDITIONAL
        else:
            raise ValueError(
                f'Invalid threshold value: "{threshold}". '
                'Must be either "unanimous" or "majority".'
            )


@dataclass
class ThinkingOutput:
    """Thinking Phaseの出力

    Attributes:
        persona_type: ペルソナタイプ
        content: 思考内容
        timestamp: タイムスタンプ
    """
    persona_type: PersonaType
    content: str
    timestamp: datetime


@dataclass
class DebateOutput:
    """Debate Phaseの出力

    Attributes:
        persona_type: ペルソナタイプ
        round_number: ラウンド番号
        responses: 他エージェントへの反論
        timestamp: タイムスタンプ
    """
    persona_type: PersonaType
    round_number: int
    responses: Dict[PersonaType, str]
    timestamp: datetime


@dataclass
class VoteOutput:
    """Voting Phaseの出力

    Attributes:
        persona_type: ペルソナタイプ
        vote: 投票結果
        reason: 理由
        conditions: CONDITIONALの場合の条件
    """
    persona_type: PersonaType
    vote: Vote
    reason: str
    conditions: Optional[List[str]] = None


@dataclass
class DebateRound:
    """Debateラウンド

    Attributes:
        round_number: ラウンド番号
        outputs: 各ペルソナの出力
        timestamp: タイムスタンプ
    """
    round_number: int
    outputs: Dict[PersonaType, DebateOutput]
    timestamp: datetime


@dataclass
class ConsensusResult:
    """合議プロセスの結果

    Attributes:
        thinking_results: Thinking Phaseの結果
        debate_results: Debate Phaseの結果
        voting_results: Voting Phaseの結果
        final_decision: 最終判定
        exit_code: 終了コード
    """
    thinking_results: Dict[str, ThinkingOutput]
    debate_results: List[DebateRound]
    voting_results: Dict[PersonaType, VoteOutput]
    final_decision: Decision
    exit_code: int
    all_conditions: Optional[List[str]] = None


@dataclass
class QuorumState:
    """クオーラム判定の状態"""

    alive: int
    quorum: int
    partial_results: bool
    retries_left: int
    excluded: List[str]


@dataclass
class StreamingEmitResult:
    """ストリーミング送出結果"""

    success: bool
    attempts: int
    last_error: Optional[Exception] = None
