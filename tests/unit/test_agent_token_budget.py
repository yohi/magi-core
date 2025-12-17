"""Agent のトークン予算連携テスト."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from magi.agents.agent import Agent
from magi.core.token_budget import TokenBudgetExceeded
from magi.models import PersonaType, Vote


class _StubPersona:
    """最小限のペルソナスタブ."""

    def __init__(self):
        self.type = PersonaType.MELCHIOR
        self.system_prompt = "system"
        self.name = "Melchior"


class _StubBudgetManager:
    """TokenBudgetManagerProtocol 互換のスタブ."""

    def __init__(self, allow: bool = True):
        self.allow = allow
        self.last_estimated = None
        self.consumed = []

    def estimate_tokens(self, text: str) -> int:
        self.last_estimated = len(text)
        return self.last_estimated

    def check_budget(self, estimated_tokens: int) -> bool:  # pragma: no cover - simple passthrough
        self.last_estimated = estimated_tokens
        return self.allow

    def consume(self, actual_tokens: int) -> None:
        self.consumed.append(actual_tokens)


class TestAgentTokenBudget(unittest.TestCase):
    """Agent が TokenBudgetManager を利用する動作を検証."""

    def test_vote_skips_llm_when_budget_exceeded(self):
        """予算超過時に LLM 呼び出しをスキップすること."""

        async def run():
            persona = _StubPersona()
            budget = _StubBudgetManager(allow=False)
            llm_client = MagicMock()
            llm_client.send = AsyncMock()
            schema_validator = MagicMock()
            agent = Agent(
                persona,
                llm_client,
                schema_validator=schema_validator,
                template_loader=None,
                security_filter=MagicMock(),
                token_budget_manager=budget,
            )

            with self.assertRaises(TokenBudgetExceeded):
                await agent.vote("dummy context")

            llm_client.send.assert_not_awaited()
            self.assertIsNotNone(budget.last_estimated)

        asyncio.run(run())

    def test_vote_consumes_tokens_after_success(self):
        """予算チェック通過後に consume が呼ばれること."""

        async def run():
            persona = _StubPersona()
            budget = _StubBudgetManager(allow=True)
            llm_client = MagicMock()
            llm_client.send = AsyncMock(
                return_value=MagicMock(
                    content='{"vote": "APPROVE", "reason": "ok", "conditions": []}'
                )
            )
            schema_validator = MagicMock()

            class _ValidationResult:
                def __init__(self):
                    self.ok = True
                    self.errors = []

            schema_validator.validate_vote_payload.return_value = _ValidationResult()

            agent = Agent(
                persona,
                llm_client,
                schema_validator=schema_validator,
                template_loader=None,
                security_filter=MagicMock(),
                token_budget_manager=budget,
            )

            result = await agent.vote("context")

            llm_client.send.assert_awaited()
            self.assertEqual(result.vote, Vote.APPROVE)
            self.assertGreaterEqual(len(budget.consumed), 1)
            self.assertIsNotNone(budget.last_estimated)

        asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover - manual execution guard
    unittest.main()
