"""クオーラム管理とストリーミング再送出のテスト（DI注入パターン）"""

import asyncio
import unittest
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

from magi.config.settings import MagiSettings
from magi.core.consensus import ConsensusEngineFactory
from magi.core.context import ContextManager
from magi.models import Decision, PersonaType, Vote, VoteOutput

# test_consensus_di_mocks.py から共通モックをインポート
from .test_consensus_di_mocks import (
    FakeConcurrencyController,
    FakeGuardrailsAdapter,
    FakeLLMClient,
    FakePersonaManager,
    FakeStreamingEmitter,
    FakeTemplateLoader,
    FakeTokenBudgetManager,
)


class TestQuorumManagerAndFailSafe(unittest.TestCase):
    """クオーラム不足時のフェイルセーフ挙動を検証する（DI注入パターン）"""

    def _create_engine(self, **settings_overrides):
        """DIファクトリを使用してエンジンを作成するヘルパー."""
        settings = MagiSettings(
            api_key="test-api-key",
            streaming_enabled=True,
            debate_rounds=1,
            quorum_threshold=settings_overrides.get("quorum_threshold", 3),
            retry_count=settings_overrides.get("retry_count", 1),
            stream_retry_count=1,
        )
        factory = ConsensusEngineFactory()
        return factory.create(
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

    def _vote_output(self, persona: PersonaType, vote: Vote = Vote.APPROVE):
        return VoteOutput(
            persona_type=persona,
            vote=vote,
            reason="ok",
            conditions=[],
        )

    def test_voting_phase_returns_fail_safe_when_below_quorum(self):
        """クオーラム未達ならフェイルセーフ応答を返し部分結果を公開しない"""
        engine = self._create_engine(quorum_threshold=3, retry_count=1)

        agents = {
            PersonaType.MELCHIOR: MagicMock(
                vote=AsyncMock(return_value=self._vote_output(PersonaType.MELCHIOR))
            ),
            PersonaType.BALTHASAR: MagicMock(
                vote=AsyncMock(return_value=self._vote_output(PersonaType.BALTHASAR))
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

        self.assertTrue(result["fail_safe"])
        self.assertEqual(Decision.DENIED, result["decision"])
        self.assertEqual(1, result["exit_code"])
        self.assertIn("quorum", result["reason"])
        self.assertIn("casper", result["excluded_agents"])
        self.assertTrue(result["partial_results"])
        # DI注入されたモックが使用されたことを確認
        self.assertGreater(len(engine.streaming_emitter.events), 0)

    def test_voting_phase_retries_failed_agent_and_succeeds(self):
        """リトライ上限内で成功すればクオーラムを満たし通常結果を返す"""
        engine = self._create_engine(quorum_threshold=2, retry_count=1)

        mel = self._vote_output(PersonaType.MELCHIOR)
        bal = self._vote_output(PersonaType.BALTHASAR)

        agents = {
            PersonaType.MELCHIOR: MagicMock(vote=AsyncMock(return_value=mel)),
            PersonaType.BALTHASAR: MagicMock(
                vote=AsyncMock(side_effect=[Exception("first"), bal])
            ),
            PersonaType.CASPER: MagicMock(
                vote=AsyncMock(side_effect=Exception("always fail"))
            ),
        }

        with unittest.mock.patch.object(
            engine, "_create_agents", return_value=agents
        ), unittest.mock.patch.object(
            engine, "_build_voting_context", return_value="ctx"
        ):
            result = asyncio.run(engine._run_voting_phase({}, []))

        self.assertFalse(result.get("fail_safe", False))
        self.assertEqual(Decision.APPROVED, result["decision"])
        self.assertEqual(0, result["exit_code"])
        # 成功した2名のみが集計される
        self.assertEqual(2, len(result["voting_results"]))
        # DI注入されたモックが使用されたことを確認
        self.assertGreater(len(engine.streaming_emitter.events), 0)


if __name__ == "__main__":
    unittest.main()
