"""DI向けモック依存でConsensusEngineを検証するユニットテスト."""

import asyncio
import unittest
import unittest.mock
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from magi.agents.persona import Persona, PersonaType
from magi.config.settings import MagiSettings
from magi.core.concurrency import ConcurrencyMetrics
from magi.core.consensus import ConsensusEngineFactory
from magi.core.context import ContextManager
from magi.core.schema_validator import SchemaValidationError
from magi.core.token_budget import BudgetResult, TokenBudgetManagerProtocol
from magi.errors import MagiException
from magi.llm.client import LLMResponse
from magi.models import ConsensusPhase, Decision, Vote, VoteOutput
from magi.security.guardrails import GuardrailsResult


class FakePersonaManager:
    """テスト用の簡易PersonaManager."""

    def __init__(self) -> None:
        self._personas: Dict[PersonaType, Persona] = {
            persona_type: Persona(
                type=persona_type,
                name=persona_type.value,
                base_prompt=f"base-{persona_type.value}",
            )
            for persona_type in PersonaType
        }

    def get_persona(self, persona_type: PersonaType) -> Persona:
        return self._personas[persona_type]

    def apply_overrides(self, overrides: Dict[str, str]) -> None:
        for persona_name, override_prompt in overrides.items():
            persona_type = {
                "melchior": PersonaType.MELCHIOR,
                "balthasar": PersonaType.BALTHASAR,
                "casper": PersonaType.CASPER,
            }.get(persona_name)
            if persona_type is None:
                continue
            existing = self._personas[persona_type]
            self._personas[persona_type] = Persona(
                type=existing.type,
                name=existing.name,
                base_prompt=existing.base_prompt,
                override_prompt=override_prompt,
            )


class FakeTokenBudgetManager(TokenBudgetManagerProtocol):
    """トークン予算管理のモック."""

    def __init__(self, max_tokens: int = 5000) -> None:
        self.max_tokens = max_tokens
        self.check_calls: List[int] = []
        self.consume_calls: List[int] = []

    def estimate_tokens(self, text: str) -> int:
        return len(text)

    def check_budget(self, estimated_tokens: int) -> bool:
        self.check_calls.append(estimated_tokens)
        return True

    def consume(self, actual_tokens: int) -> None:
        self.consume_calls.append(actual_tokens)

    def enforce(self, context: str, phase: ConsensusPhase) -> BudgetResult:
        return BudgetResult(
            context=context,
            summary_applied=False,
            reduced_tokens=0,
            logs=[],
        )


class FakeTemplateRevision:
    def __init__(self) -> None:
        self.version = "fake-version"
        self.template = "{context}"
        self.variables: Dict[str, str] = {"context": "{context}"}


class FakeTemplateLoader:
    def __init__(self) -> None:
        self._hook = None

    def set_event_hook(self, hook) -> None:
        self._hook = hook

    def cached(self, name: str) -> FakeTemplateRevision:
        return FakeTemplateRevision()

    def load(self, name: str) -> FakeTemplateRevision:
        return FakeTemplateRevision()


class FakeLLMClient:
    """LLMClientのモック。ネットワークを使用しない."""

    def __init__(self, temperature: float = 0.7) -> None:
        self.sent_prompts: List[str] = []
        self.temperature = temperature

    async def send(self, request) -> LLMResponse:
        self.sent_prompts.append(request.user_prompt)
        if "Voting Phase" in request.user_prompt:
            content = '{"vote": "APPROVE", "reason": "ok", "conditions": []}'
        else:
            content = f"応答: {request.user_prompt}"
        return LLMResponse(content=content, usage={"input_tokens": 0, "output_tokens": 0}, model="fake")


class FakeStreamingEmitter:
    """ストリーミング送出のモック."""

    def __init__(self) -> None:
        self.events: List[tuple] = []
        self.started = False
        self.closed = False
        self.dropped = 0

    async def start(self) -> None:
        self.started = True

    async def emit(self, persona: str, content: str, phase: str, round_number=None, priority: str = "normal") -> None:
        self.events.append((persona, phase, content, round_number, priority))

    async def aclose(self) -> None:
        self.closed = True


class FakeGuardrailsAdapter:
    """ガードレール判定のモック."""

    def __init__(self, *, blocked: bool = False):
        self.blocked = blocked

    async def check(self, prompt: str) -> GuardrailsResult:
        return GuardrailsResult(
            blocked=self.blocked,
            reason="blocked" if self.blocked else None,
            provider="fake",
            failure=None,
            fail_open=False,
            metadata={},
        )


class FakeConcurrencyController:
    """同時実行制御のモック."""

    def __init__(self, max_concurrent: int = 10) -> None:
        self.max_concurrent = max_concurrent
        self.acquire_calls: List[Optional[float]] = []
        self._total_acquired = 0
        self._total_timeouts = 0
        self._total_rate_limits = 0

    def acquire(self, timeout: Optional[float] = None):
        """同時実行許可を取得するコンテキストマネージャのモック."""
        from contextlib import asynccontextmanager

        self_ref = self

        @asynccontextmanager
        async def _acquire():
            self_ref.acquire_calls.append(timeout)
            self_ref._total_acquired += 1
            try:
                yield
            finally:
                pass

        return _acquire()

    def get_metrics(self) -> ConcurrencyMetrics:
        """現在のメトリクスを返す."""
        return ConcurrencyMetrics(
            active_count=0,
            waiting_count=0,
            total_acquired=self._total_acquired,
            total_timeouts=self._total_timeouts,
            total_rate_limits=self._total_rate_limits,
        )

    def note_rate_limit(self) -> None:
        """レート制限発生を記録する."""
        self._total_rate_limits += 1


class TestConsensusEngineWithMocks(unittest.TestCase):
    """DI向けモック依存を用いたConsensusEngineテスト."""

    def _create_engine(self, **overrides):
        settings = MagiSettings(api_key="dummy-key", streaming_enabled=True, debate_rounds=1)
        factory = ConsensusEngineFactory()
        return factory.create(
            settings,
            persona_manager=overrides.get("persona_manager", FakePersonaManager()),
            context_manager=overrides.get("context_manager", ContextManager()),
            template_loader=overrides.get("template_loader", FakeTemplateLoader()),
            llm_client_factory=overrides.get("llm_client_factory", lambda: FakeLLMClient()),
            guardrails_adapter=overrides.get("guardrails_adapter", FakeGuardrailsAdapter()),
            streaming_emitter=overrides.get("streaming_emitter", FakeStreamingEmitter()),
            concurrency_controller=overrides.get("concurrency_controller", FakeConcurrencyController()),
            token_budget_manager=overrides.get("token_budget_manager", FakeTokenBudgetManager()),
        )

    def test_execute_with_mock_dependencies(self):
        """モック依存を注入して合議フローが完了すること."""
        engine = self._create_engine()

        result = asyncio.run(engine.execute("テストプロンプト"))

        self.assertIsInstance(result.final_decision, Decision)
        self.assertTrue(engine.streaming_emitter.started)
        self.assertGreater(len(engine.streaming_emitter.events), 0)
        self.assertGreater(len(engine.token_budget_manager.check_calls), 0)
        self.assertGreater(len(engine.token_budget_manager.consume_calls), 0)

    def test_execute_blocked_by_guardrails(self):
        """ガードレールがブロック時に例外を返すこと."""
        engine = self._create_engine(
            guardrails_adapter=FakeGuardrailsAdapter(blocked=True),
        )
        engine.config.guardrails_enabled = True

        with self.assertRaises(MagiException):
            asyncio.run(engine.execute("危険な入力"))

    def test_execute_quorum_not_reached(self):
        """クオーラム未達時にフェイルセーフ応答を返すこと."""
        # クオーラムを3に設定
        settings = MagiSettings(
            api_key="dummy-key",
            streaming_enabled=True,
            debate_rounds=1,
            quorum_threshold=3,
            retry_count=1,
        )
        factory = ConsensusEngineFactory()
        engine = factory.create(
            settings,
            persona_manager=FakePersonaManager(),
            context_manager=ContextManager(),
            template_loader=FakeTemplateLoader(),
            llm_client_factory=lambda: FakeLLMClient(),
            guardrails_adapter=FakeGuardrailsAdapter(),
            streaming_emitter=FakeStreamingEmitter(),
            concurrency_controller=FakeConcurrencyController(),
            token_budget_manager=FakeTokenBudgetManager(),
        )

        # 2つのエージェントは成功、1つは失敗するようモック
        def _vote_output(persona: PersonaType) -> VoteOutput:
            return VoteOutput(
                persona_type=persona,
                vote=Vote.APPROVE,
                reason="ok",
                conditions=[],
            )

        agents = {
            PersonaType.MELCHIOR: MagicMock(
                vote=AsyncMock(return_value=_vote_output(PersonaType.MELCHIOR))
            ),
            PersonaType.BALTHASAR: MagicMock(
                vote=AsyncMock(return_value=_vote_output(PersonaType.BALTHASAR))
            ),
            PersonaType.CASPER: MagicMock(
                vote=AsyncMock(side_effect=Exception("network failure"))
            ),
        }

        with unittest.mock.patch.object(
            engine, "_create_agents", return_value=agents
        ), unittest.mock.patch.object(
            engine, "_build_voting_context", return_value="ctx"
        ):
            result = asyncio.run(engine._run_voting_phase({}, []))

        # フェイルセーフで拒否されること
        self.assertTrue(result["fail_safe"])
        self.assertEqual(Decision.DENIED, result["decision"])
        self.assertEqual(1, result["exit_code"])
        self.assertIn("quorum", result["reason"])
        # ストリーミングが使用されたことを確認
        self.assertGreater(len(engine.streaming_emitter.events), 0)

    def test_execute_schema_retry_exhausted(self):
        """スキーマ検証リトライ枯渇時にエラーが記録されること."""
        # リトライ回数を0に設定
        settings = MagiSettings(
            api_key="dummy-key",
            streaming_enabled=True,
            debate_rounds=1,
            schema_retry_count=0,
        )
        factory = ConsensusEngineFactory()
        engine = factory.create(
            settings,
            persona_manager=FakePersonaManager(),
            context_manager=ContextManager(),
            template_loader=FakeTemplateLoader(),
            llm_client_factory=lambda: FakeLLMClient(),
            guardrails_adapter=FakeGuardrailsAdapter(),
            streaming_emitter=FakeStreamingEmitter(),
            concurrency_controller=FakeConcurrencyController(),
            token_budget_manager=FakeTokenBudgetManager(),
        )

        # 全エージェントがスキーマ検証エラーを返すようモック
        agent = MagicMock()
        agent.vote = AsyncMock(side_effect=SchemaValidationError(["invalid schema"]))

        agents = {
            PersonaType.MELCHIOR: agent,
            PersonaType.BALTHASAR: MagicMock(
                vote=AsyncMock(side_effect=SchemaValidationError(["invalid schema"]))
            ),
            PersonaType.CASPER: MagicMock(
                vote=AsyncMock(side_effect=SchemaValidationError(["invalid schema"]))
            ),
        }

        with unittest.mock.patch.object(
            engine, "_create_agents", return_value=agents
        ), unittest.mock.patch.object(
            engine, "_build_voting_context", return_value="ctx"
        ):
            result = asyncio.run(engine._run_voting_phase({}, []))

        # 投票結果が空でエラーが記録されること
        self.assertEqual(result["voting_results"], {})
        self.assertGreaterEqual(len(engine.errors), 1)
        # ストリーミングが使用されたことを確認
        self.assertGreater(len(engine.streaming_emitter.events), 0)


if __name__ == "__main__":
    unittest.main()
