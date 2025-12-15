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
import inspect
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from magi.agents.agent import Agent
from magi.agents.persona import PersonaManager
from magi.config.manager import Config
from magi.core.concurrency import ConcurrencyController, ConcurrencyLimitError
from magi.core.context import ContextManager
from magi.core.quorum import QuorumManager
from magi.core.schema_validator import SchemaValidationError, SchemaValidator
from magi.core.template_loader import TemplateLoader
from magi.core.token_budget import ReductionLog, TokenBudgetManager
from magi.errors import ErrorCode, MagiError, MagiException, create_agent_error
from magi.llm.client import LLMClient
from magi.core.streaming import (
    NullStreamingEmitter,
    QueueStreamingEmitter,
    StreamChunk,
)
from magi.security.filter import SecurityFilter
from magi.security.guardrails import GuardrailsAdapter
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


class VotingStrategy(Protocol):
    """Voting 処理を切り替えるための Strategy インターフェース"""

    name: str

    async def run(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
    ) -> Dict:
        """Voting 処理を実行する"""


class HardenedVotingStrategy:
    """ハードニング済み Voting Strategy"""

    name = "hardened"

    def __init__(
        self,
        executor: Callable[
            [Dict[PersonaType, ThinkingOutput], List[DebateRound]], Awaitable[Dict]
        ],
    ) -> None:
        self._executor = executor

    async def run(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
    ) -> Dict:
        return await self._executor(thinking_results, debate_results)


class LegacyVotingStrategy:
    """レガシー Voting Strategy"""

    name = "legacy"

    def __init__(
        self,
        executor: Callable[
            [Dict[PersonaType, ThinkingOutput], List[DebateRound]], Awaitable[Dict]
        ],
    ) -> None:
        self._executor = executor

    async def run(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
    ) -> Dict:
        return await self._executor(thinking_results, debate_results)


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
        llm_client_factory: Optional[Callable[[], LLMClient]] = None,
        guardrails_adapter: Optional[GuardrailsAdapter] = None,
        streaming_emitter: Optional[Any] = None,
        event_context: Optional[Dict[str, Any]] = None,
        concurrency_controller: Optional[ConcurrencyController] = None,
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
        self._event_context = self._sanitize_event_context(event_context)
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
        if guardrails_adapter is not None:
            self.guardrails = guardrails_adapter
        else:
            self.guardrails = GuardrailsAdapter(
                timeout_seconds=getattr(
                    self.config,
                    "guardrails_timeout_seconds",
                    3,
                ),
                on_timeout_behavior=getattr(
                    self.config,
                    "guardrails_on_timeout_behavior",
                    "fail-closed",
                ),
                on_error_policy=getattr(
                    self.config,
                    "guardrails_on_error_policy",
                    "fail-closed",
                ),
                enabled=getattr(self.config, "enable_guardrails", False),
            )
        # 同時実行制御
        limit = getattr(self.config, "llm_concurrency_limit", 1)
        self.concurrency_controller = concurrency_controller or ConcurrencyController(
            max_concurrent=limit
        )
        self._concurrency_timeout_seconds = getattr(self.config, "timeout", None)
        # LLMクライアントのファクトリ（デフォルトは設定値から生成）
        if llm_client_factory is None:
            self.llm_client_factory = self._build_default_llm_client_factory()
        elif callable(llm_client_factory):
            self.llm_client_factory = llm_client_factory
        else:
            # LLMClient インスタンスが渡された場合はラップして再利用する
            self.llm_client_factory = lambda: llm_client_factory

        # エラーログを保持
        self._errors: List[Dict] = []
        # コンテキスト削減ログを保持
        self._reduction_logs: List[ReductionLog] = []
        # トークン予算マネージャ
        self.token_budget_manager = TokenBudgetManager(
            max_tokens=self.config.token_budget
        )
        # ストリーミング出力設定
        self._streaming_enabled = getattr(self.config, "enable_streaming_output", False)
        if streaming_emitter is not None:
            self.streaming_emitter = streaming_emitter
        elif self._streaming_enabled:
            self.streaming_emitter = self._build_default_streaming_emitter()
        else:
            self.streaming_emitter = NullStreamingEmitter()
        self._streaming_state = {
            "enabled": self._streaming_enabled,
            "fail_safe": False,
            "fail_safe_reason": None,
            "emitted": 0,
            "dropped": 0,
            "started_at": None,
            "first_emit_at": None,
            "completed_at": None,
            "ttfb_ms": None,
            "elapsed_ms": None,
        }
        self._stream_buffer: List[str] = []
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
        llm_client = self.llm_client_factory()

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

    def _build_default_llm_client_factory(self) -> Callable[[], LLMClient]:
        """設定値に基づくデフォルトLLMクライアントファクトリを構築"""
        def _factory() -> LLMClient:
            return LLMClient(
                api_key=self.config.api_key,
                model=self.config.model,
                retry_count=self.config.retry_count,
                timeout=self.config.timeout,
                concurrency_controller=self.concurrency_controller,
            )

        return _factory

    def _log_concurrency_metrics(
        self,
        phase: ConsensusPhase,
        persona_type: Optional[PersonaType],
    ) -> None:
        """同時実行メトリクスをログに記録する."""
        if self.concurrency_controller is None:
            return

        metrics = self.concurrency_controller.get_metrics()
        logger.info(
            (
                "consensus.concurrency.metrics phase=%s persona=%s "
                "active=%s waiting=%s acquired=%s timeouts=%s rate_limits=%s"
            ),
            phase.value if isinstance(phase, ConsensusPhase) else phase,
            persona_type.value if persona_type else None,
            metrics.active_count,
            metrics.waiting_count,
            metrics.total_acquired,
            metrics.total_timeouts,
            metrics.total_rate_limits,
        )

    async def _run_with_concurrency(
        self,
        phase: ConsensusPhase,
        persona_type: Optional[PersonaType],
        func: Callable[[], Awaitable[Any]],
        *,
        quorum_sensitive: bool = False,
    ):
        """ConcurrencyController を介して処理を実行する."""
        if self.concurrency_controller is None:
            return await func()

        persona_value = persona_type.value if persona_type else None
        try:
            async with self.concurrency_controller.acquire(
                timeout=self._concurrency_timeout_seconds
            ):
                result = await func()
            self._log_concurrency_metrics(phase, persona_type)
            return result
        except ConcurrencyLimitError as exc:
            self._errors.append(
                {
                    "phase": phase.value if isinstance(phase, ConsensusPhase) else phase,
                    "persona_type": persona_value,
                    "error": str(exc),
                    "type": "concurrency_limit",
                }
            )
            self._record_event(
                "concurrency.limit",
                phase=phase.value if isinstance(phase, ConsensusPhase) else phase,
                persona=persona_value,
                message=str(exc),
            )
            logger.warning(
                "consensus.concurrency.limit phase=%s persona=%s",
                phase.value if isinstance(phase, ConsensusPhase) else phase,
                persona_value,
            )
            self._log_concurrency_metrics(phase, persona_type)
            if quorum_sensitive and persona_value is not None:
                self.quorum_manager.exclude(persona_value)
            return None

    async def _emit_debate_streaming_output(
        self,
        persona_type: PersonaType,
        output: DebateOutput,
        round_number: int,
    ) -> bool:
        """Debate 出力をストリーミング送出し、トークン予算を監視する。"""
        if not self._streaming_enabled:
            return True

        await self.streaming_emitter.start()
        for response in output.responses.values():
            await self.streaming_emitter.emit(
                persona_type.value,
                response,
                ConsensusPhase.DEBATE.value,
                round_number,
            )
            self._streaming_state["emitted"] += 1
            self._stream_buffer.append(response)
            if self._streaming_state.get("first_emit_at") is None:
                now = time.perf_counter()
                self._streaming_state["first_emit_at"] = now
                started = self._streaming_state.get("started_at")
                if started is not None:
                    self._streaming_state["ttfb_ms"] = (now - started) * 1000

            estimated = self.token_budget_manager.estimate_tokens(
                "".join(self._stream_buffer)
            )
            if estimated > self.token_budget_manager.max_tokens:
                self._streaming_state["fail_safe"] = True
                self._streaming_state["fail_safe_reason"] = "token_budget_exceeded"
                self._streaming_state["completed_at"] = time.perf_counter()
                started = self._streaming_state.get("started_at")
                completed = self._streaming_state.get("completed_at")
                if started is not None and completed is not None:
                    self._streaming_state["elapsed_ms"] = (completed - started) * 1000
                self._record_event(
                    "debate.streaming.aborted",
                    code=ErrorCode.CONSENSUS_STREAMING_ABORTED.value,
                    phase=ConsensusPhase.DEBATE.value,
                    reason="token_budget_exceeded",
                    round=round_number,
                    estimated_tokens=estimated,
                    budget=self.token_budget_manager.max_tokens,
                )
                self._errors.append(
                    {
                        "code": ErrorCode.CONSENSUS_STREAMING_ABORTED.value,
                        "phase": ConsensusPhase.DEBATE.value,
                        "reason": "token_budget_exceeded",
                        "round_number": round_number,
                        "estimated_tokens": estimated,
                    }
                )
                return False
        return True

    def _build_default_streaming_emitter(self) -> QueueStreamingEmitter:
        """設定値ベースのストリーミングエミッタを構築."""

        async def _log_send(chunk: StreamChunk) -> None:
            logger.info(
                "consensus.debate.stream persona=%s phase=%s round=%s size=%s",
                chunk.persona,
                chunk.phase,
                chunk.round_number,
                len(chunk.chunk),
            )

        return QueueStreamingEmitter(
            send_func=_log_send,
            queue_size=getattr(self.config, "streaming_queue_size", 100),
            emit_timeout_seconds=getattr(
                self.config, "streaming_emit_timeout_seconds", 2.0
            ),
        )

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
                return await self._run_with_concurrency(
                    ConsensusPhase.THINKING,
                    persona_type,
                    lambda: agent.think(prompt),
                )
            except Exception as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                # エラーを記録
                error_info = {
                    "phase": ConsensusPhase.THINKING.value,
                    "persona_type": persona_type.value,
                    "error": str(e),
                }
                self._errors.append(error_info)
                logger.exception(
                    "エージェント %s の思考生成に失敗", persona_type.value
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

        self._stream_buffer = []
        self._streaming_state.update(
            {
                "enabled": self._streaming_enabled,
                "fail_safe": False,
                "fail_safe_reason": None,
                "emitted": 0,
                "dropped": 0,
                "started_at": None,
                "first_emit_at": None,
                "completed_at": None,
                "ttfb_ms": None,
                "elapsed_ms": None,
            }
        )
        stop_streaming = False
        agents = self._create_agents()
        debate_rounds: List[DebateRound] = []
        if self._streaming_enabled:
            self._streaming_state["started_at"] = time.perf_counter()

        try:
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
                    """エラーハンドリング付きのDebate実行"""
                    try:
                        return await self._run_with_concurrency(
                            ConsensusPhase.DEBATE,
                            persona_type,
                            lambda: agent.debate(others_thoughts, round_number),
                        )
                    except Exception as e:
                        if isinstance(e, (KeyboardInterrupt, SystemExit)):
                            raise
                        # エラーを記録
                        error_info = {
                            "phase": ConsensusPhase.DEBATE.value,
                            "persona_type": persona_type.value,
                            "round_number": round_number,
                            "error": str(e),
                        }
                        self._errors.append(error_info)
                        logger.exception(
                            "エージェント %s のDebate（ラウンド%s）に失敗",
                            persona_type.value,
                            round_number,
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
                        if self._streaming_enabled and not stop_streaming:
                            should_continue = await self._emit_debate_streaming_output(
                                persona_type,
                                output,
                                round_num,
                            )
                            if not should_continue:
                                stop_streaming = True
                                break

                # ラウンド結果を追加
                debate_round = DebateRound(
                    round_number=round_num,
                    outputs=round_outputs,
                    timestamp=datetime.now()
                )
                debate_rounds.append(debate_round)

                logger.info(f"Debateラウンド {round_num} 完了")
                if stop_streaming:
                    logger.warning(
                        "Debate ストリーミングを中断しました: reason=%s",
                        self._streaming_state.get("fail_safe_reason"),
                    )
                    break
        finally:
            if hasattr(self.streaming_emitter, "dropped"):
                try:
                    self._streaming_state["dropped"] = self.streaming_emitter.dropped
                except Exception:
                    self._streaming_state["dropped"] = 0
            if self._streaming_enabled:
                await self.streaming_emitter.aclose()

        if self._streaming_enabled:
            if self._streaming_state.get("completed_at") is None:
                self._streaming_state["completed_at"] = time.perf_counter()
            started = self._streaming_state.get("started_at")
            completed = self._streaming_state.get("completed_at")
            if started is not None and completed is not None:
                self._streaming_state["elapsed_ms"] = (completed - started) * 1000
            self._record_event(
                "debate.streaming.summary",
                phase=ConsensusPhase.DEBATE.value,
                emitted=self._streaming_state["emitted"],
                dropped=self._streaming_state.get("dropped", 0),
                fail_safe=self._streaming_state["fail_safe"],
                fail_safe_reason=self._streaming_state["fail_safe_reason"],
                ttfb_ms=self._streaming_state.get("ttfb_ms"),
                elapsed_ms=self._streaming_state.get("elapsed_ms"),
            )

        # フェーズをVOTINGに遷移
        self._transition_to_phase(ConsensusPhase.VOTING)

        return debate_rounds

    async def _run_voting_phase(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
    ) -> Dict:
        """Voting Strategy を選択し実行する"""
        strategy = self._select_voting_strategy()
        result = await strategy.run(thinking_results, debate_results)

        meta = result.setdefault(
            "meta",
            {},
        )
        meta.setdefault(
            "strategy",
            getattr(strategy, "name", strategy.__class__.__name__.lower()),
        )
        fallback_used = bool(result.get("legacy_fallback_used"))
        fallback_meta = meta.setdefault("fallback", {})
        fallback_meta["used"] = fallback_used
        if fallback_meta.get("used"):
            fallback_meta["strategy"] = fallback_meta.get("strategy") or "legacy"
            fallback_meta["reason"] = (
                result.get("fail_safe_reason") or result.get("reason")
            )
        else:
            fallback_meta["strategy"] = None
            fallback_meta["reason"] = None

        meta.setdefault("excluded_agents", result.get("excluded_agents", []))
        meta.setdefault("partial_results", result.get("partial_results", False))
        meta.setdefault("summary_applied", result.get("summary_applied", False))
        return result

    def _select_voting_strategy(self) -> VotingStrategy:
        """設定値に応じて Voting Strategy を選択する"""
        if getattr(self.config, "enable_hardened_consensus", True):
            return HardenedVotingStrategy(self._run_voting_phase_hardened)
        return LegacyVotingStrategy(self._run_voting_phase_legacy)

    async def _run_voting_phase_hardened(
        self,
        thinking_results: Dict[PersonaType, ThinkingOutput],
        debate_results: List[DebateRound],
    ) -> Dict:
        """ハードニング済み Voting Strategy を実行する"""
        from magi.models import VotingTally

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

        # トークン予算を適用
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
                    retain_ratio=log_item.retain_ratio,
                    summary_applied=log_item.summary_applied,
                    strategy=log_item.strategy,
                )
            if self.config.log_context_reduction_key:  # pragma: no cover - on by default path
                for log_item in budget_result.logs:
                    logger.info(
                        (
                            "consensus.context.reduced phase=%s reason=%s "
                            "before=%s after=%s retain_ratio=%.3f "
                            "summary_applied=%s strategy=%s"
                        ),
                        log_item.phase,
                        log_item.reason,
                        log_item.before_tokens,
                        log_item.after_tokens,
                        log_item.retain_ratio,
                        log_item.summary_applied,
                        log_item.strategy,
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
                            vote_output = await self._run_with_concurrency(
                                ConsensusPhase.VOTING,
                                persona_type,
                                lambda: agent.vote(context),
                                quorum_sensitive=True,
                            )
                            if vote_output is None:
                                failed_personas.append(persona_type.value)
                                return None
                            return vote_output
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
                                        "code": ErrorCode.CONSENSUS_SCHEMA_RETRY_EXCEEDED.value,
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
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
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
                    logger.exception(
                        "エージェント %s の投票に失敗 (attempt=%s)",
                        persona_type.value,
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
            fail_safe_reason = "quorum_fail_safe"
            self._errors.append(
                {
                    "code": ErrorCode.CONSENSUS_QUORUM_UNSATISFIED.value,
                    "phase": ConsensusPhase.VOTING.value,
                    "reason": reason,
                    "excluded": failed_personas,
                }
            )
            self._record_event(
                "quorum.fail_safe",
                code=ErrorCode.CONSENSUS_QUORUM_UNSATISFIED.value,
                phase=ConsensusPhase.VOTING.value,
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
                    phase=ConsensusPhase.VOTING.value,
                    used=bool(fallback.get("voting_results")),
                    excluded=sorted(set(failed_personas)),
                )
                fallback["legacy_fallback_used"] = True
                fallback["fail_safe_reason"] = fail_safe_reason
                fallback["reason"] = reason
                fallback.setdefault("excluded_agents", sorted(set(failed_personas)))
                fallback.setdefault("partial_results", partial_results)
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
                "fail_safe_reason": fail_safe_reason,
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
                return await self._run_with_concurrency(
                    ConsensusPhase.VOTING,
                    persona_type,
                    lambda: agent.vote(context),
                    quorum_sensitive=True,
                )
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
        gather_result = asyncio.gather(*tasks)
        if inspect.isawaitable(gather_result):
            outputs = await gather_result
        else:
            # モックで同期オブジェクトが返るケースに備えてコルーチンを破棄
            for task in tasks:
                if inspect.iscoroutine(task):
                    task.close()
            outputs = gather_result

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

    async def _run_guardrails(self, prompt: str) -> None:
        """Guardrails を SecurityFilter 前段で実行する."""
        if not getattr(self.config, "enable_guardrails", False):
            return

        result = await self.guardrails.check(prompt)
        provider = result.provider or "unknown"

        if result.failure:
            event_type = (
                "guardrails.fail_open" if result.fail_open else "guardrails.blocked"
            )
            failure_code = (
                ErrorCode.GUARDRAILS_TIMEOUT.value
                if result.failure == "timeout"
                else ErrorCode.GUARDRAILS_ERROR.value
            )
            self._record_event(
                event_type,
                code=failure_code,
                phase="preflight",
                provider=provider,
                failure=result.failure,
                reason=result.reason,
            )
            if result.fail_open:
                logger.warning(
                    "guardrails.fail_open provider=%s failure=%s", provider, result.failure
                )
                return
            raise MagiException(
                MagiError(
                    code=failure_code,
                    message="Guardrails により処理を中断しました。",
                    details={
                        "provider": provider,
                        "failure": result.failure,
                        "reason": result.reason,
                    },
                    recoverable=False,
                )
            )

        if result.blocked:
            self._record_event(
                "guardrails.blocked",
                code=ErrorCode.GUARDRAILS_BLOCKED.value,
                phase="preflight",
                provider=provider,
                reason=result.reason,
                metadata=result.metadata,
            )
            raise MagiException(
                MagiError(
                    code=ErrorCode.GUARDRAILS_BLOCKED.value,
                    message="Guardrails により入力が拒否されました。",
                    details={
                        "provider": provider,
                        "reason": result.reason,
                        "metadata": result.metadata,
                    },
                    recoverable=False,
                )
            )

        if result.fail_open:
            self._record_event(
                "guardrails.fail_open",
                code=(
                    ErrorCode.GUARDRAILS_TIMEOUT.value
                    if result.failure == "timeout"
                    else ErrorCode.GUARDRAILS_ERROR.value
                ),
                phase="preflight",
                provider=provider,
                failure=result.failure,
            )
            logger.warning(
                "guardrails.fail_open provider=%s failure=%s", provider, result.failure
            )

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
        await self._run_guardrails(prompt)

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
        context = dict(self._event_context)
        event = {**context, "type": event_type, **payload}
        self._events.append(event)

    def set_event_context(
        self,
        *,
        provider: Optional[str] = None,
        missing_fields: Optional[Any] = None,
        auth_error: Optional[Any] = None,
    ) -> None:
        """イベントに付与するコンテキストを更新"""
        updates = {
            "provider": provider,
            "missing_fields": missing_fields,
            "auth_error": auth_error,
        }
        self._event_context.update(
            self._sanitize_event_context({k: v for k, v in updates.items() if v is not None})
        )

    @property
    def events(self) -> List[Dict[str, Any]]:
        """イベントログを取得"""
        return self._events.copy()

    @property
    def streaming_state(self) -> Dict[str, Any]:
        """ストリーミング状態を取得."""
        return self._streaming_state.copy()

    @property
    def context_reduction_logs(self) -> List[ReductionLog]:
        """コンテキスト削減ログを取得."""
        return self._reduction_logs.copy()

    def _sanitize_event_context(
        self, context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """イベントに付与するコンテキストをフィルタ"""
        if not context:
            return {}
        allowed_keys = {"provider", "missing_fields", "auth_error"}
        return {k: v for k, v in context.items() if k in allowed_keys}
