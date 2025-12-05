"""合議プロトコルの実行エンジン

MAGIシステムの中核となる合議プロトコル（Thinking → Debate → Voting）を管理する。
3つのエージェント（MELCHIOR、BALTHASAR、CASPER）による合議プロセスを実行し、
最終判定を決定する。

Requirements:
    - 4.1: 3つのエージェントに対して独立した思考生成を要求
    - 4.2: 各エージェントが他のエージェントの出力を参照できない状態で思考を生成
    - 4.3: 全エージェントが思考を完了すると3つの独立した思考結果を収集し次のフェーズに進む
    - 4.4: エージェントの思考生成が失敗した場合、エラーを記録し残りのエージェントの処理を継続
    - 5.3: 設定されたラウンド数に達するとDebate Phaseを終了しVoting Phaseに移行
    - 6.1: APPROVE、DENY、CONDITIONALのいずれかの投票を要求
    - 6.2: 全エージェントが投票を完了すると投票結果を集計し最終判定を決定
"""

import asyncio
import logging
from typing import Dict, List, Optional

from magi.agents.agent import Agent
from magi.agents.persona import PersonaManager
from magi.config.manager import Config
from magi.core.context import ContextManager
from magi.llm.client import LLMClient
from magi.models import (
    ConsensusPhase,
    ConsensusResult,
    DebateRound,
    Decision,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
)

# ロガーの設定
logger = logging.getLogger(__name__)


class ConsensusEngine:
    """合議プロトコルの実行エンジン

    3つのエージェント（MELCHIOR、BALTHASAR、CASPER）による合議プロセスを
    管理・実行する。Thinking → Debate → Votingの3フェーズを経て
    最終判定を決定する。

    Attributes:
        config: MAGI設定
        persona_manager: ペルソナマネージャー
        context_manager: コンテキストマネージャー
        current_phase: 現在のフェーズ
    """

    def __init__(self, config: Config):
        """ConsensusEngineを初期化

        Args:
            config: MAGI設定
        """
        self.config = config
        self.persona_manager = PersonaManager()
        self.context_manager = ContextManager()
        self.current_phase = ConsensusPhase.THINKING

        # エラーログを保持
        self._errors: List[Dict] = []

    def _transition_to_phase(self, phase: ConsensusPhase) -> None:
        """指定されたフェーズに遷移

        Args:
            phase: 遷移先のフェーズ
        """
        logger.info(f"フェーズ遷移: {self.current_phase.value} -> {phase.value}")
        self.current_phase = phase

    def _create_agents(self) -> Dict[PersonaType, Agent]:
        """3つのエージェントを作成

        Returns:
            ペルソナタイプをキーとするAgentの辞書
        """
        llm_client = LLMClient(
            api_key=self.config.api_key,
            model=self.config.model,
            retry_count=self.config.retry_count,
            timeout=self.config.timeout
        )

        agents = {}
        for persona_type in PersonaType:
            persona = self.persona_manager.get_persona(persona_type)
            agents[persona_type] = Agent(persona, llm_client)

        return agents

    async def _run_thinking_phase(self, prompt: str) -> Dict[PersonaType, ThinkingOutput]:
        """Thinking Phaseを実行

        各エージェントに対して独立した思考生成を要求し、結果を収集する。
        エージェントの思考生成が失敗した場合は、エラーを記録し、
        残りのエージェントの処理を継続する。

        Requirements:
            - 4.1: 3つのエージェントに対して独立した思考生成を要求
            - 4.2: 各エージェントが他のエージェントの出力を参照できない状態で思考を生成
            - 4.3: 全エージェントが思考を完了すると3つの独立した思考結果を収集し次のフェーズに進む
            - 4.4: エージェントの思考生成が失敗した場合、エラーを記録し残りのエージェントの処理を継続

        Args:
            prompt: ユーザーからのプロンプト

        Returns:
            各ペルソナタイプに対応するThinkingOutputの辞書
        """
        agents = self._create_agents()
        results: Dict[PersonaType, ThinkingOutput] = {}

        # 各エージェントに対して独立した思考生成を要求
        # asyncio.gather を使って並列実行
        async def think_with_error_handling(
            persona_type: PersonaType,
            agent: Agent
        ) -> Optional[ThinkingOutput]:
            """エラーハンドリング付きの思考生成

            Args:
                persona_type: ペルソナタイプ
                agent: エージェント

            Returns:
                ThinkingOutput または失敗時はNone
            """
            try:
                return await agent.think(prompt)
            except Exception as e:
                # エラーを記録
                error_info = {
                    "phase": ConsensusPhase.THINKING.value,
                    "persona_type": persona_type.value,
                    "error": str(e),
                }
                self._errors.append(error_info)
                logger.error(
                    f"エージェント {persona_type.value} の思考生成に失敗: {e}"
                )
                return None

        # 全エージェントの思考を並列実行
        tasks = [
            think_with_error_handling(persona_type, agent)
            for persona_type, agent in agents.items()
        ]

        thinking_outputs = await asyncio.gather(*tasks)

        # 結果を辞書に格納（成功したもののみ）
        for persona_type, output in zip(agents.keys(), thinking_outputs):
            if output is not None:
                results[persona_type] = output

        # フェーズをDEBATEに遷移
        self._transition_to_phase(ConsensusPhase.DEBATE)

        return results

    async def execute(
        self,
        prompt: str,
        plugin: Optional[object] = None
    ) -> ConsensusResult:
        """合議プロセスを実行

        Thinking → Debate → Votingの3フェーズを経て最終判定を決定する。

        Args:
            prompt: ユーザーからのプロンプト
            plugin: プラグイン（オプション）

        Returns:
            ConsensusResult: 合議結果
        """
        # プラグインのオーバーライドを適用
        if plugin is not None and hasattr(plugin, 'agent_overrides'):
            self.persona_manager.apply_overrides(plugin.agent_overrides)

        # Thinking Phaseを実行
        thinking_results = await self._run_thinking_phase(prompt)

        # TODO: Debate Phaseを実行（Task 8.6で実装）
        debate_results: List[DebateRound] = []

        # TODO: Voting Phaseを実行（Task 8.9で実装）
        voting_results: Dict[str, Vote] = {}

        # TODO: 最終判定を決定（Task 8.9で実装）
        final_decision = Decision.CONDITIONAL
        exit_code = 0

        # フェーズをCOMPLETEDに遷移
        self._transition_to_phase(ConsensusPhase.COMPLETED)

        return ConsensusResult(
            thinking_results=thinking_results,
            debate_results=debate_results,
            voting_results=voting_results,
            final_decision=final_decision,
            exit_code=exit_code
        )

    @property
    def errors(self) -> List[Dict]:
        """エラーログを取得

        Returns:
            エラーログのリスト
        """
        return self._errors.copy()
