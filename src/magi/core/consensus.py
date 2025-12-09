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
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from magi.agents.agent import Agent
from magi.agents.persona import PersonaManager
from magi.config.manager import Config
from magi.core.context import ContextManager
from magi.core.quorum import QuorumManager
from magi.core.schema_validator import SchemaValidationError, SchemaValidator
from magi.core.template_loader import TemplateLoader
from magi.core.token_budget import ReductionLog, TokenBudgetManager
from magi.errors import MagiException, create_agent_error
from magi.llm.client import LLMClient
from magi.security.filter import SecurityFilter
from magi.models import (
    ConsensusPhase,
    ConsensusResult,
    DebateOutput,
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

    def __init__(
        self,
        config: Config,
        schema_validator: Optional[SchemaValidator] = None,
        template_loader: Optional[TemplateLoader] = None,
    ):
        """ConsensusEngineを初期化

        Args:
            config: MAGI設定
        """
        self.config = config
        self.persona_manager = PersonaManager()
        self.context_manager = ContextManager()
        self.current_phase = ConsensusPhase.THINKING
        self.schema_validator = schema_validator or SchemaValidator()
        self._events: List[Dict[str, Any]] = []
        if template_loader is not None:
            self.template_loader = template_loader
            # 既存インスタンスでもイベントを収集できるようにフックを差し込む
            if hasattr(self.template_loader, "set_event_hook"):
                self.template_loader.set_event_hook(self._record_event)
        else:
            self.template_loader = TemplateLoader(
                Path(self.config.template_base_path),
                ttl_seconds=self.config.template_ttl_seconds,
                schema_validator=self.schema_validator,
                event_hook=self._record_event,
            )
        self.security_filter = SecurityFilter()

        # エラーログを保持
        self._errors: List[Dict] = []
        # コンテキスト削減ログを保持
        self._reduction_logs: List[ReductionLog] = []
        # トークン予算マネージャ
        self.token_budget_manager = TokenBudgetManager(
            max_tokens=self.config.token_budget
        )
        # クオーラム管理
        self.quorum_manager = QuorumManager(
            total_agents=len(PersonaType),
            quorum=self.config.quorum_threshold,
            max_retries=self.config.retry_count,
        )

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
            agents[persona_type] = Agent(
                persona,
                llm_client,
                schema_validator=self.schema_validator,
                template_loader=self.template_loader,
                security_filter=self.security_filter,
            )

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

    async def _run_debate_phase(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput]
    ) -> List[DebateRound]:
        """Debate Phaseを実行

        Thinking Phaseの結果を受け取り、設定されたラウンド数だけ
        議論を行う。各エージェントは他の2つのエージェントの思考結果を
        参照して反論または補足を生成する。

        Requirements:
            - 5.1: 各エージェントに他の2つのエージェントの思考結果を提供
            - 5.2: 他のエージェントの意見に対する反論または補足を出力
            - 5.3: 設定されたラウンド数に達するとVoting Phaseに移行
            - 5.4: ラウンド数が設定されていない場合はデフォルトで1ラウンド

        Args:
            thinking_results: Thinking Phaseの結果

        Returns:
            List[DebateRound]: 各ラウンドのDebate結果
        """
        from datetime import datetime

        agents = self._create_agents()
        debate_rounds: List[DebateRound] = []

        # 設定されたラウンド数だけDebateを実行
        for round_num in range(1, self.config.debate_rounds + 1):
            logger.info(f"Debateラウンド {round_num} 開始")

            # 各ラウンドの結果を収集
            round_outputs: Dict[PersonaType, DebateOutput] = {}

            async def debate_with_error_handling(
                persona_type: PersonaType,
                agent: Agent,
                others_thoughts: Dict[PersonaType, str],
                round_number: int
            ) -> Optional[DebateOutput]:
                """エラーハンドリング付きのDebate実行

                Args:
                    persona_type: ペルソナタイプ
                    agent: エージェント
                    others_thoughts: 他エージェントの思考内容
                    round_number: ラウンド番号

                Returns:
                    DebateOutput または失敗時はNone
                """
                try:
                    return await agent.debate(others_thoughts, round_number)
                except Exception as e:
                    # エラーを記録
                    error_info = {
                        "phase": ConsensusPhase.DEBATE.value,
                        "persona_type": persona_type.value,
                        "round_number": round_number,
                        "error": str(e),
                    }
                    self._errors.append(error_info)
                    logger.error(
                        f"エージェント {persona_type.value} のDebate（ラウンド{round_number}）に失敗: {e}"
                    )
                    return None

            # 各エージェントに他のエージェントの思考を提供してDebateを実行
            tasks = []
            for persona_type, agent in agents.items():
                # 他のエージェントの思考結果を抽出（自分自身は除外）
                others_thoughts = {
                    pt: thinking_results[pt].content
                    for pt in thinking_results.keys()
                    if pt != persona_type
                }

                tasks.append(
                    debate_with_error_handling(
                        persona_type, agent, others_thoughts, round_num
                    )
                )

            # 全エージェントのDebateを並列実行
            debate_outputs = await asyncio.gather(*tasks)

            # 結果を辞書に格納（成功したもののみ）
            for persona_type, output in zip(agents.keys(), debate_outputs):
                if output is not None:
                    round_outputs[persona_type] = output

            # ラウンド結果を追加
            debate_round = DebateRound(
                round_number=round_num,
                outputs=round_outputs,
                timestamp=datetime.now()
            )
            debate_rounds.append(debate_round)

            logger.info(f"Debateラウンド {round_num} 完了")

        # フェーズをVOTINGに遷移
        self._transition_to_phase(ConsensusPhase.VOTING)

        return debate_rounds

    async def _run_voting_phase(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
    ) -> Dict:
        """Voting Phaseを実行"""
        from magi.models import VotingTally

        # フラグ無効なら旧経路を使用
        if not getattr(self.config, "enable_hardened_consensus", True):
            return await self._run_voting_phase_legacy(
                thinking_results, debate_results, mark_fallback=False
            )

        agents = self._create_agents()
        self.quorum_manager = QuorumManager(
            total_agents=len(agents),
            quorum=self.config.quorum_threshold,
            max_retries=self.config.retry_count,
        )
        effective_quorum = min(self.config.quorum_threshold, len(agents))

        failed_personas: List[str] = []
        voting_results: Dict[PersonaType, VoteOutput] = {}

        # 議論コンテキストを構築
        context = self._build_voting_context(thinking_results, debate_results)

        # トークン予算を適用 (新経路のみ)
        budget_result = self.token_budget_manager.enforce(
            context, ConsensusPhase.VOTING
        )
        summary_applied = budget_result.summary_applied
        if budget_result.summary_applied:
            self._reduction_logs.extend(budget_result.logs)
            for log_item in budget_result.logs:
                self._record_event(
                    "context.reduced",
                    phase=log_item.phase,
                    reason=log_item.reason,
                    before_tokens=log_item.before_tokens,
                    after_tokens=log_item.after_tokens,
                )
            if self.config.log_context_reduction_key:  # pragma: no cover - on by default path
                for log_item in budget_result.logs:
                    logger.info(
                        "consensus.context.reduced phase=%s reason=%s before=%s after=%s",
                        log_item.phase,
                        log_item.reason,
                        log_item.before_tokens,
                        log_item.after_tokens,
                    )
            else:
                logger.info("consensus.context.reduced detail_log=disabled")
            context = budget_result.context

        async def vote_with_error_handling(
            persona_type: PersonaType, agent: Agent
        ) -> Optional[VoteOutput]:
            """エラーハンドリング付きの投票実行"""
            payload_id = uuid.uuid4().hex
            template_revision = self.template_loader.cached(
                self.config.vote_template_name
            )
            template_version = (
                template_revision.version if template_revision else "unknown"
            )
            max_schema_retry = self.config.schema_retry_count

            for attempt in range(0, self.config.retry_count + 1):
                schema_attempt = 0
                try:
                    while True:
                        try:
                            return await agent.vote(context)
                        except SchemaValidationError as e:
                            schema_attempt += 1
                            self._record_event(
                                "schema.retry",
                                persona=persona_type.value,
                                attempt=schema_attempt,
                                max=max_schema_retry,
                                template_version=template_version,
                                payload_id=payload_id,
                                errors=e.errors,
                            )
                            logger.warning(
                                "consensus.schema.validation_failed payload_id=%s persona=%s "
                                "attempt=%s max=%s template_version=%s errors=%s",
                                payload_id,
                                persona_type.value,
                                schema_attempt,
                                max_schema_retry,
                                template_version,
                                ";".join(e.errors),
                            )
                            if schema_attempt > max_schema_retry:
                                self._record_event(
                                    "schema.retry_exhausted",
                                    retry_count=schema_attempt - 1,
                                    max=max_schema_retry,
                                    template_version=template_version,
                                    payload_id=payload_id,
                                    persona=persona_type.value,
                                )
                                logger.warning(
                                    "consensus.schema.retry_exhausted retry_count=%s max=%s "
                                    "template_version=%s payload_id=%s",
                                    schema_attempt - 1,
                                    max_schema_retry,
                                    template_version,
                                    payload_id,
                                )
                                self._record_event(
                                    "schema.rejected", payload_id=payload_id
                                )
                                logger.error(
                                    "consensus.schema.rejected payload_id=%s", payload_id
                                )
                                self._errors.append(
                                    {
                                        "code": "CONSENSUS_SCHEMA_RETRY_EXCEEDED",
                                        "phase": ConsensusPhase.VOTING.value,
                                        "persona_type": persona_type.value,
                                        "errors": e.errors,
                                        "payload_id": payload_id,
                                        "template_version": template_version,
                                    }
                                )
                                failed_personas.append(persona_type.value)
                                self.quorum_manager.exclude(persona_type.value)
                                return None
                            continue
                except Exception as e:  # pragma: no cover - リトライロジックで検証
                    error_info = {
                        "phase": ConsensusPhase.VOTING.value,
                        "persona_type": persona_type.value,
                        "error": str(e),
                        "attempt": attempt + 1,
                    }
                    self._errors.append(error_info)
                    self._record_event(
                        "vote.error",
                        persona=persona_type.value,
                        attempt=attempt + 1,
                        message=str(e),
                    )
                    logger.error(
                        "エージェント %s の投票に失敗: %s (attempt=%s)",
                        persona_type.value,
                        e,
                        attempt + 1,
                    )
                    if attempt >= self.config.retry_count:
                        break
                    continue
            failed_personas.append(persona_type.value)
            self.quorum_manager.exclude(persona_type.value)
            return None

        # 全エージェントの投票を並列実行
        tasks = [
            vote_with_error_handling(persona_type, agent)
            for persona_type, agent in agents.items()
        ]
        vote_outputs = await asyncio.gather(*tasks)

        # 結果を辞書に格納（成功したもののみ）
        for persona_type, output in zip(agents.keys(), vote_outputs):
            if output is not None:
                voting_results[persona_type] = output
                self.quorum_manager.note_success(persona_type.value)

        partial_results = 0 < len(voting_results) < len(agents)
        if len(voting_results) < effective_quorum:
            reason = "quorum 未達によりフェイルセーフ"
            self._errors.append(
                {
                    "code": "CONSENSUS_QUORUM_UNSATISFIED",
                    "phase": ConsensusPhase.VOTING.value,
                    "reason": reason,
                    "excluded": failed_personas,
                }
            )
            self._record_event(
                "quorum.fail_safe",
                reason=reason,
                excluded=sorted(set(failed_personas)),
                partial_results=partial_results,
            )
            if getattr(self.config, "legacy_fallback_on_fail_safe", False):
                fallback = await self._run_voting_phase_legacy(
                    thinking_results,
                    debate_results,
                    context_override=context,
                    agents_override=agents,
                    mark_fallback=True,
                )
                fallback.setdefault("meta", {})["hardened_fail_safe"] = True
                if summary_applied:
                    # ハードニング経路で要約が適用された場合はフォールバック結果にも反映
                    fallback["summary_applied"] = True
                self._record_event(
                    "quorum.fallback_legacy",
                    used=bool(fallback.get("voting_results")),
                    excluded=sorted(set(failed_personas)),
                )
                return fallback

            return {
                "voting_results": {},
                "decision": Decision.DENIED,
                "exit_code": 1,
                "all_conditions": [],
                "summary_applied": summary_applied,
                "context": context,
                "fail_safe": True,
                "reason": reason,
                "excluded_agents": sorted(set(failed_personas)),
                "partial_results": partial_results,
                "legacy_fallback_used": False,
            }

        # 投票を集計
        approve_count = sum(
            1 for v in voting_results.values() if v.vote == Vote.APPROVE
        )
        deny_count = sum(1 for v in voting_results.values() if v.vote == Vote.DENY)
        conditional_count = sum(
            1 for v in voting_results.values() if v.vote == Vote.CONDITIONAL
        )

        tally = VotingTally(
            approve_count=approve_count,
            deny_count=deny_count,
            conditional_count=conditional_count,
        )

        decision = tally.get_decision(self.config.voting_threshold)
        if decision == Decision.APPROVED:
            exit_code = 0
        elif decision == Decision.DENIED:
            exit_code = 1
        else:
            exit_code = 2

        all_conditions = []
        for vote_output in voting_results.values():
            if vote_output.vote == Vote.CONDITIONAL and vote_output.conditions:
                all_conditions.extend(vote_output.conditions)

        self._transition_to_phase(ConsensusPhase.COMPLETED)

        logger.info(f"Voting Phase完了: {decision.value} (Exit Code: {exit_code})")

        return {
            "voting_results": voting_results,
            "decision": decision,
            "exit_code": exit_code,
            "all_conditions": all_conditions,
            "summary_applied": summary_applied,
            "context": context,
            "fail_safe": False,
            "excluded_agents": sorted(set(failed_personas)),
            "partial_results": partial_results,
            "legacy_fallback_used": False,
        }

    async def _run_voting_phase_legacy(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
        context_override: Optional[str] = None,
        agents_override: Optional[Dict[PersonaType, Agent]] = None,
        mark_fallback: bool = False,
    ) -> Dict:
        """旧経路でのVoting実行

        ハードニング無効またはフェイルセーフ時のフォールバック用。
        """
        from magi.models import VotingTally

        agents = agents_override or self._create_agents()
        context = (
            context_override
            if context_override is not None
            else self._build_voting_context(thinking_results, debate_results)
        )

        voting_results: Dict[PersonaType, VoteOutput] = {}
        failed_personas: List[str] = []

        async def vote_once(persona_type: PersonaType, agent: Agent) -> Optional[VoteOutput]:
            try:
                return await agent.vote(context)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self._errors.append(
                    {
                        "phase": ConsensusPhase.VOTING.value,
                        "persona_type": persona_type.value,
                        "error": str(exc),
                        "mode": "legacy",
                    }
                )
                return None

        tasks = [
            vote_once(persona_type, agent)
            for persona_type, agent in agents.items()
        ]
        outputs = await asyncio.gather(*tasks)

        if sys.version_info >= (3, 10):
            persona_outputs = zip(agents.keys(), outputs, strict=True)
        else:
            if len(agents) != len(outputs):
                raise ValueError(
                    f"投票結果数が不一致: agents={len(agents)} outputs={len(outputs)}"
                )
            persona_outputs = zip(agents.keys(), outputs)

        for persona_type, output in persona_outputs:
            if output is not None:
                voting_results[persona_type] = output
            else:
                failed_personas.append(persona_type.value)

        partial_results = 0 < len(voting_results) < len(agents)
        if not voting_results:
            # 旧経路でも票が得られない場合はフェイルセーフ
            return {
                "voting_results": {},
                "decision": Decision.DENIED,
                "exit_code": 1,
                "all_conditions": [],
                "summary_applied": False,
                "context": context,
                "fail_safe": True,
                "reason": "legacy path quorum不足",
                "excluded_agents": sorted(set(failed_personas)),
                "partial_results": partial_results,
                "legacy_mode": True,
                "legacy_fallback_used": mark_fallback,
            }

        approve_count = sum(
            1 for v in voting_results.values() if v.vote == Vote.APPROVE
        )
        deny_count = sum(1 for v in voting_results.values() if v.vote == Vote.DENY)
        conditional_count = sum(
            1 for v in voting_results.values() if v.vote == Vote.CONDITIONAL
        )

        tally = VotingTally(
            approve_count=approve_count,
            deny_count=deny_count,
            conditional_count=conditional_count,
        )
        decision = tally.get_decision(self.config.voting_threshold)
        if decision == Decision.APPROVED:
            exit_code = 0
        elif decision == Decision.DENIED:
            exit_code = 1
        else:
            exit_code = 2

        all_conditions = []
        for vote_output in voting_results.values():
            if vote_output.vote == Vote.CONDITIONAL and vote_output.conditions:
                all_conditions.extend(vote_output.conditions)

        return {
            "voting_results": voting_results,
            "decision": decision,
            "exit_code": exit_code,
            "all_conditions": all_conditions,
            "summary_applied": False,
            "context": context,
            "fail_safe": False,
            "excluded_agents": sorted(set(failed_personas)),
            "partial_results": partial_results,
            "legacy_mode": True,
            "legacy_fallback_used": mark_fallback,
        }

    def _build_voting_context(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound]
    ) -> str:
        """投票用のコンテキストを構築

        Args:
            thinking_results: Thinking Phaseの結果
            debate_results: Debate Phaseの結果

        Returns:
            str: 議論コンテキスト
        """
        context_parts = []

        # Thinking結果を追加
        context_parts.append("【Thinking Phase結果】")
        for persona_type, output in thinking_results.items():
            persona_name = self._get_persona_name(persona_type)
            context_parts.append(f"\n[{persona_name}の思考]")
            context_parts.append(output.content)

        # Debate結果を追加
        if debate_results:
            context_parts.append("\n【Debate Phase結果】")
            for debate_round in debate_results:
                context_parts.append(f"\n--- ラウンド {debate_round.round_number} ---")
                for persona_type, output in debate_round.outputs.items():
                    persona_name = self._get_persona_name(persona_type)
                    context_parts.append(f"\n[{persona_name}の意見]")
                    # responsesの内容を追加
                    for target_type, response in output.responses.items():
                        target_name = self._get_persona_name(target_type)
                        context_parts.append(f"  {target_name}への反論: {response[:200]}...")

        return "\n".join(context_parts)

    def _get_persona_name(self, persona_type: PersonaType) -> str:
        """PersonaTypeからペルソナ名を取得

        Args:
            persona_type: ペルソナタイプ

        Returns:
            str: ペルソナ名
        """
        name_map = {
            PersonaType.MELCHIOR: "MELCHIOR-1",
            PersonaType.BALTHASAR: "BALTHASAR-2",
            PersonaType.CASPER: "CASPER-3",
        }
        return name_map.get(persona_type, persona_type.value)

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
        detection = self.security_filter.detect_abuse(prompt)
        if detection.blocked:
            logger.warning(
                "consensus.input.rejected rules=%s",
                ",".join(detection.matched_rules),
            )
            raise MagiException(
                create_agent_error(
                    "入力に禁止パターンが含まれているため処理を中断しました。",
                    details={"rules": detection.matched_rules},
                )
            )

        # プラグインのオーバーライドを適用
        if plugin is not None and hasattr(plugin, 'agent_overrides'):
            self.persona_manager.apply_overrides(plugin.agent_overrides)

        # Thinking Phaseを実行
        thinking_results = await self._run_thinking_phase(prompt)

        # Debate Phaseを実行
        debate_results = await self._run_debate_phase(thinking_results)

        # Voting Phaseを実行
        voting_result = await self._run_voting_phase(thinking_results, debate_results)

        # 結果を抽出
        voting_results = voting_result["voting_results"]
        final_decision = voting_result["decision"]
        exit_code = voting_result["exit_code"]

        # 注意: _run_voting_phase 内で既にCOMPLETEDに遷移済み

        return ConsensusResult(
            thinking_results=thinking_results,
            debate_results=debate_results,
            voting_results=voting_results,
            final_decision=final_decision,
            exit_code=exit_code,
            all_conditions=voting_result["all_conditions"]
        )

    @property
    def errors(self) -> List[Dict]:
        """エラーログを取得

        Returns:
            エラーログのリスト
        """
        return self._errors.copy()

    def _record_event(self, event_type: str, **payload: Any) -> None:
        """構造化イベントを記録する"""
        event = {"type": event_type, **payload}
        self._events.append(event)

    @property
    def events(self) -> List[Dict[str, Any]]:
        """イベントログを取得"""
        return self._events.copy()

    @property
    def context_reduction_logs(self) -> List[ReductionLog]:
        """コンテキスト削減ログを取得."""
        return self._reduction_logs.copy()
