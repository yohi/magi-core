"""クオーラム管理とストリーミング再送出のテスト"""

import asyncio
import unittest
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine, StreamingEmitter
from magi.core.quorum import QuorumManager
from magi.models import Decision, PersonaType, Vote, VoteOutput


class TestQuorumManagerAndFailSafe(unittest.TestCase):
    """クオーラム不足時のフェイルセーフ挙動を検証する"""

    def _vote_output(self, persona: PersonaType, vote: Vote = Vote.APPROVE):
        return VoteOutput(
            persona_type=persona,
            vote=vote,
            reason="ok",
            conditions=[],
        )

    def test_voting_phase_returns_fail_safe_when_below_quorum(self):
        """クオーラム未達ならフェイルセーフ応答を返し部分結果を公開しない"""
        config = Config(
            api_key="test-api-key",
            quorum_threshold=3,
            retry_count=1,
            stream_retry_count=1,
        )
        engine = ConsensusEngine(config)

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

    def test_voting_phase_retries_failed_agent_and_succeeds(self):
        """リトライ上限内で成功すればクオーラムを満たし通常結果を返す"""
        config = Config(
            api_key="test-api-key",
            quorum_threshold=2,
            retry_count=1,
            stream_retry_count=1,
        )
        engine = ConsensusEngine(config)

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


class TestStreamingEmitter(unittest.TestCase):
    """ストリーミング再送出のリトライを検証する"""

    def test_emit_retries_on_failure_and_succeeds(self):
        """最初の送出に失敗してもリトライ回数内なら成功する"""
        calls = {"count": 0}

        def sink(chunk: str, phase: str):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("first fail")
            return True

        emitter = StreamingEmitter(retry_count=2, sink=sink)
        emitter.emit("token", phase="voting")

        self.assertEqual(2, calls["count"])

    def test_emit_gives_up_after_max_retry(self):
        """リトライ上限超過でエラーを返す"""

        def sink(chunk: str, phase: str):
            raise RuntimeError("always")

        emitter = StreamingEmitter(retry_count=2, sink=sink)
        result = emitter.emit("token", phase="voting")

        self.assertFalse(result.success)
        self.assertEqual(2, result.attempts)


if __name__ == "__main__":
    unittest.main()
