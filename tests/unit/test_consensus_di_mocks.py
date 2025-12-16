"""DI向けモック依存でConsensusEngineを検証するユニットテスト."""

import asyncio
import unittest
from typing import Dict, List, Optional

from magi.agents.persona import Persona, PersonaType
from magi.config.settings import MagiSettings
from magi.core.consensus import ConsensusEngineFactory
from magi.core.context import ContextManager
from magi.core.token_budget import BudgetResult, TokenBudgetManagerProtocol
from magi.errors import MagiException
from magi.llm.client import LLMResponse
from magi.models import ConsensusPhase, Decision
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

    def enforce(self, context: str, phase: ConsensusPhase) -> BudgetResult:  # type: ignore[override]
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

    def __init__(self) -> None:
        self.sent_prompts: List[str] = []

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


if __name__ == "__main__":
    unittest.main()
