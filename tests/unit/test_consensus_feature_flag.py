"""ConsensusEngine の feature flag とイベント集約のテスト"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.core.schema_validator import SchemaValidationError
from magi.models import Decision, PersonaType, Vote, VoteOutput


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

    def test_legacy_zip_strict_raises_on_length_mismatch_py310_plus(self):
        """Python 3.10+ で zip(strict=True) が長さ不一致を検知する"""
        config = Config(api_key="test-api-key", enable_hardened_consensus=False)
        engine = ConsensusEngine(config)

        agent = MagicMock()
        agent.vote = AsyncMock(return_value=VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="ok",
        ))

        with patch.object(
            engine, "_build_voting_context", return_value="ctx"
        ), patch.object(
            engine, "_create_agents", return_value={PersonaType.MELCHIOR: agent}
        ), patch(
            "magi.core.consensus.asyncio.gather", return_value=[]
        ), patch(
            "magi.core.consensus.sys.version_info", (3, 10, 0, "final", 0)
        ):
            with self.assertRaises(ValueError):
                asyncio.run(engine._run_voting_phase_legacy({}, []))

    def test_legacy_zip_len_check_raises_on_length_mismatch_pre310(self):
        """Python 3.9 互換経路で長さ不一致を検知する"""
        config = Config(api_key="test-api-key", enable_hardened_consensus=False)
        engine = ConsensusEngine(config)

        agent = MagicMock()
        agent.vote = AsyncMock(return_value=VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="ok",
        ))

        with patch.object(
            engine, "_build_voting_context", return_value="ctx"
        ), patch.object(
            engine, "_create_agents", return_value={PersonaType.MELCHIOR: agent}
        ), patch(
            "magi.core.consensus.asyncio.gather", return_value=[]
        ), patch(
            "magi.core.consensus.sys.version_info", (3, 9, 9, "final", 0)
        ):
            with self.assertRaisesRegex(
                ValueError, "投票結果数が不一致: agents=1 outputs=0"
            ):
                asyncio.run(engine._run_voting_phase_legacy({}, []))


class TestVotingStrategySelection(unittest.TestCase):
    """Voting Strategy の選択とフォールバックメタ情報を検証する"""

    def test_hardened_strategy_is_selected_when_flag_enabled(self):
        """ハードニング有効時に HardenedVotingStrategy が選択される"""
        config = Config(api_key="test-api-key", enable_hardened_consensus=True)
        engine = ConsensusEngine(config)

        with patch("magi.core.consensus.HardenedVotingStrategy") as mock_strategy:
            strategy_instance = mock_strategy.return_value
            strategy_instance.name = "hardened"
            strategy_instance.run = AsyncMock(
                return_value={
                    "voting_results": {},
                    "decision": Decision.DENIED,
                    "exit_code": 1,
                    "all_conditions": [],
                    "summary_applied": False,
                    "context": "ctx",
                    "fail_safe": False,
                    "excluded_agents": [],
                    "partial_results": False,
                    "legacy_fallback_used": False,
                }
            )

            result = asyncio.run(engine._run_voting_phase({}, []))

        mock_strategy.assert_called_once()
        strategy_instance.run.assert_awaited_once_with({}, [])
        self.assertEqual(result["meta"]["strategy"], "hardened")
        self.assertFalse(result["meta"]["fallback"]["used"])

    def test_legacy_strategy_is_selected_when_flag_disabled(self):
        """ハードニング無効時に LegacyVotingStrategy が選択される"""
        config = Config(api_key="test-api-key", enable_hardened_consensus=False)
        engine = ConsensusEngine(config)

        with patch("magi.core.consensus.LegacyVotingStrategy") as mock_strategy:
            strategy_instance = mock_strategy.return_value
            strategy_instance.name = "legacy"
            strategy_instance.run = AsyncMock(
                return_value={
                    "voting_results": {},
                    "decision": Decision.DENIED,
                    "exit_code": 1,
                    "all_conditions": [],
                    "summary_applied": False,
                    "context": "ctx",
                    "fail_safe": False,
                    "excluded_agents": [],
                    "partial_results": False,
                    "legacy_fallback_used": False,
                }
            )

            result = asyncio.run(engine._run_voting_phase({}, []))

        mock_strategy.assert_called_once()
        strategy_instance.run.assert_awaited_once_with({}, [])
        self.assertEqual(result["meta"]["strategy"], "legacy")
        self.assertFalse(result["meta"]["fallback"]["used"])

    def test_fallback_meta_is_recorded_on_quorum_fail_safe(self):
        """クオーラム未達でレガシーへフォールバックした場合にメタが記録される"""
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

        self.assertEqual(result["meta"]["strategy"], "hardened")
        self.assertTrue(result["meta"]["fallback"]["used"])
        self.assertEqual(result["meta"]["fallback"]["strategy"], "legacy")
        self.assertEqual(result["meta"]["fallback"]["reason"], "quorum_fail_safe")
        self.assertTrue(result["legacy_fallback_used"])


if __name__ == "__main__":
    unittest.main()
