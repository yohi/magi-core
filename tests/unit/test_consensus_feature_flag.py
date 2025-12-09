"""ConsensusEngine の feature flag とイベント集約のテスト"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.core.schema_validator import SchemaValidationError
from magi.models import PersonaType, Vote, VoteOutput


class TestConsensusFeatureFlag(unittest.TestCase):
    """ハードニング有無の挙動を検証する"""

    def test_legacy_mode_skips_budget_and_quorum(self):
        """ハードニング無効時は要約せずクオーラムで失敗しない"""
        config = Config(
            api_key="test-api-key",
            token_budget=8,
            quorum_threshold=3,
            enable_hardened_consensus=False,
        )
        engine = ConsensusEngine(config)

        long_context = "長文" * 200  # 本来なら予算超過
        agent = MagicMock()
        agent.vote = AsyncMock(
            return_value=VoteOutput(
                persona_type=PersonaType.MELCHIOR,
                vote=Vote.APPROVE,
                reason="ok",
            )
        )

        with patch.object(
            engine, "_build_voting_context", return_value=long_context
        ), patch.object(
            engine,
            "_create_agents",
            return_value={PersonaType.MELCHIOR: agent},
        ):
            result = asyncio.run(engine._run_voting_phase({}, []))

        self.assertFalse(result["summary_applied"])
        self.assertFalse(result["fail_safe"])
        self.assertEqual(result["context"], long_context)
        self.assertEqual(engine.context_reduction_logs, [])
        self.assertEqual(
            result["voting_results"][PersonaType.MELCHIOR].vote, Vote.APPROVE
        )

    def test_fail_safe_fallback_uses_legacy_when_enabled(self):
        """クオーラム未達時にレガシー経路へフォールバックできる"""
        config = Config(
            api_key="test-api-key",
            quorum_threshold=2,
            enable_hardened_consensus=True,
            legacy_fallback_on_fail_safe=True,
        )
        engine = ConsensusEngine(config)

        success = MagicMock()
        success.vote = AsyncMock(
            return_value=VoteOutput(
                persona_type=PersonaType.MELCHIOR,
                vote=Vote.APPROVE,
                reason="ok",
            )
        )
        failure = MagicMock()
        failure.vote = AsyncMock(side_effect=Exception("vote failed"))

        with patch.object(
            engine, "_build_voting_context", return_value="ctx"
        ), patch.object(
            engine,
            "_create_agents",
            return_value={
                PersonaType.MELCHIOR: success,
                PersonaType.BALTHASAR: failure,
            },
        ):
            result = asyncio.run(engine._run_voting_phase({}, []))

        self.assertFalse(result["fail_safe"])
        self.assertTrue(result.get("legacy_fallback_used"))
        self.assertIn(PersonaType.MELCHIOR, result["voting_results"])
        self.assertEqual(
            result["voting_results"][PersonaType.MELCHIOR].vote, Vote.APPROVE
        )

    def test_event_log_collects_reduction_and_schema_retry(self):
        """削減とスキーマリトライ枯渇がイベントに記録される"""
        config = Config(
            api_key="test-api-key",
            token_budget=6,
            schema_retry_count=0,
        )
        engine = ConsensusEngine(config)

        long_context = "要約対象" * 300
        agent = MagicMock()
        agent.vote = AsyncMock(
            side_effect=[SchemaValidationError(["invalid payload"])]
        )

        with patch.object(
            engine, "_build_voting_context", return_value=long_context
        ), patch.object(
            engine,
            "_create_agents",
            return_value={PersonaType.MELCHIOR: agent},
        ):
            _ = asyncio.run(engine._run_voting_phase({}, []))

        event_types = [event["type"] for event in engine.events]
        self.assertIn("context.reduced", event_types)
        self.assertIn("schema.retry_exhausted", event_types)
        self.assertIn("schema.rejected", event_types)


if __name__ == "__main__":
    unittest.main()
