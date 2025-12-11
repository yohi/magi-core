"""合議エンジンの統合・回帰・性能計測テスト."""

import asyncio
import unittest
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable
from unittest.mock import AsyncMock, MagicMock, patch

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.errors import ErrorCode
from magi.models import (
    DebateOutput,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
)
from magi.security.filter import DetectionResult
from magi.security.guardrails import GuardrailsResult


@dataclass(frozen=True)
class FlagMatrixCase:
    """フラグ組み合わせの入力と期待."""

    enable_hardened_consensus: bool
    enable_streaming_output: bool
    enable_guardrails: bool
    legacy_fallback_on_fail_safe: bool


class RecordingEmitter:
    """テスト用ストリーミングエミッタ."""

    def __init__(self, emit_delay: float = 0.0) -> None:
        self.chunks: list[tuple[str, str, str, int | None]] = []
        self.started = False
        self.closed = False
        self.dropped = 0
        self._emit_delay = emit_delay

    async def start(self) -> "RecordingEmitter":
        self.started = True
        return self

    async def emit(
        self,
        persona: str,
        chunk: str,
        phase: str,
        round_number: int | None = None,
    ) -> None:
        if self._emit_delay:
            await asyncio.sleep(self._emit_delay)
        self.chunks.append((persona, chunk, phase, round_number))

    async def aclose(self) -> None:
        self.closed = True


class StaticGuardrailsAdapter:
    """固定結果を返すガードレールアダプタ."""

    def __init__(self, result: GuardrailsResult) -> None:
        self._result = result
        self.check_calls = 0

    async def check(self, prompt: str) -> GuardrailsResult:
        self.check_calls += 1
        return self._result


class TestConsensusFlagMatrix(unittest.IsolatedAsyncioTestCase):
    """主要フラグ組み合わせの後方互換を確認する."""

    def _simple_thinking(self) -> Dict[PersonaType, ThinkingOutput]:
        now = datetime.now()
        return {
            PersonaType.MELCHIOR: ThinkingOutput(
                persona_type=PersonaType.MELCHIOR,
                content="m",
                timestamp=now,
            ),
            PersonaType.BALTHASAR: ThinkingOutput(
                persona_type=PersonaType.BALTHASAR,
                content="b",
                timestamp=now,
            ),
        }

    def _simple_vote_output(self) -> VoteOutput:
        return VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="ok",
        )

    async def test_flag_matrix_respects_strategy_and_guardrails(self) -> None:
        """フラグ組み合わせごとに戦略・ガードレール・ストリーミング設定を維持する."""
        cases: Iterable[FlagMatrixCase] = [
            FlagMatrixCase(True, True, False, False),
            FlagMatrixCase(False, False, True, False),
            FlagMatrixCase(True, False, True, True),
            FlagMatrixCase(False, True, False, True),
        ]

        for case in cases:
            with self.subTest(case=case):
                config = Config(
                    api_key="key",
                    enable_hardened_consensus=case.enable_hardened_consensus,
                    enable_streaming_output=case.enable_streaming_output,
                    enable_guardrails=case.enable_guardrails,
                    legacy_fallback_on_fail_safe=case.legacy_fallback_on_fail_safe,
                    quorum_threshold=2,
                )
                guardrails = StaticGuardrailsAdapter(
                    GuardrailsResult(
                        blocked=False,
                        reason=None,
                        provider="stub",
                        failure=None,
                        fail_open=case.enable_guardrails is False,
                    )
                )
                engine = ConsensusEngine(config, guardrails_adapter=guardrails)

                detection = DetectionResult(blocked=False, matched_rules=[])
                with patch.object(
                    engine.security_filter, "detect_abuse", return_value=detection
                ):
                    await engine._run_guardrails("prompt")

                self.assertEqual(
                    guardrails.check_calls,
                    1 if case.enable_guardrails else 0,
                    "ガードレール有効時のみ check が呼ばれるべき",
                )
                self.assertEqual(
                    engine.streaming_state["enabled"],
                    case.enable_streaming_output,
                )

                vote_output = self._simple_vote_output()
                agents = {
                    PersonaType.MELCHIOR: MagicMock(vote=AsyncMock(return_value=vote_output)),
                    PersonaType.BALTHASAR: MagicMock(vote=AsyncMock(return_value=vote_output)),
                }
                thinking = {
                    PersonaType.MELCHIOR: ThinkingOutput(
                        persona_type=PersonaType.MELCHIOR,
                        content="m",
                        timestamp=datetime.now(),
                    ),
                    PersonaType.BALTHASAR: ThinkingOutput(
                        persona_type=PersonaType.BALTHASAR,
                        content="b",
                        timestamp=datetime.now(),
                    ),
                }

                with patch.object(engine, "_create_agents", return_value=agents):
                    result = await engine._run_voting_phase(thinking, [])

                expected_strategy = (
                    "hardened" if case.enable_hardened_consensus else "legacy"
                )
                self.assertEqual(result["meta"]["strategy"], expected_strategy)


class TestConsensusEventCodes(unittest.IsolatedAsyncioTestCase):
    """イベントにエラーコードとフェーズが付与されていることを確認する."""

    async def test_streaming_guardrails_and_quorum_events_have_codes(self) -> None:
        """ストリーミング中断/ガードレール/クオーラム失敗イベントにコードを付与する."""
        # ストリーミング中断
        streaming_config = Config(
            api_key="key",
            debate_rounds=1,
            enable_streaming_output=True,
            token_budget=5,
            streaming_queue_size=10,
        )
        emitter = RecordingEmitter()
        engine_stream = ConsensusEngine(streaming_config, streaming_emitter=emitter)
        long_text = "x" * 100
        outputs = {
            PersonaType.MELCHIOR: DebateOutput(
                persona_type=PersonaType.MELCHIOR,
                round_number=1,
                responses={PersonaType.BALTHASAR: long_text},
                timestamp=datetime.now(),
            ),
            PersonaType.BALTHASAR: DebateOutput(
                persona_type=PersonaType.BALTHASAR,
                round_number=1,
                responses={PersonaType.MELCHIOR: long_text},
                timestamp=datetime.now(),
            ),
        }
        agents = {
            persona: MagicMock(debate=AsyncMock(return_value=output))
            for persona, output in outputs.items()
        }
        thinking = {
            PersonaType.MELCHIOR: ThinkingOutput(
                persona_type=PersonaType.MELCHIOR,
                content="m",
                timestamp=datetime.now(),
            ),
            PersonaType.BALTHASAR: ThinkingOutput(
                persona_type=PersonaType.BALTHASAR,
                content="b",
                timestamp=datetime.now(),
            ),
        }
        with patch.object(engine_stream, "_create_agents", return_value=agents):
            await engine_stream._run_debate_phase(thinking)

        streaming_event = next(
            evt for evt in engine_stream.events if evt["type"] == "debate.streaming.aborted"
        )
        self.assertEqual(
            streaming_event["code"], ErrorCode.CONSENSUS_STREAMING_ABORTED.value
        )
        self.assertEqual(streaming_event["phase"], "debate")

        # ガードレール fail-open（タイムアウト）イベント
        guardrails_config = Config(
            api_key="key",
            enable_guardrails=True,
        )
        guardrails_adapter = StaticGuardrailsAdapter(
            GuardrailsResult(
                blocked=False,
                reason="timeout",
                provider="stub",
                failure="timeout",
                fail_open=True,
            )
        )
        engine_guard = ConsensusEngine(guardrails_config, guardrails_adapter=guardrails_adapter)
        await engine_guard._run_guardrails("prompt")

        guard_event = next(
            evt for evt in engine_guard.events if evt["type"] == "guardrails.fail_open"
        )
        self.assertEqual(guard_event["code"], ErrorCode.GUARDRAILS_TIMEOUT.value)
        self.assertEqual(guard_event["provider"], "stub")
        self.assertEqual(guard_event["phase"], "preflight")

        # クオーラム未達イベント
        quorum_config = Config(
            api_key="key",
            enable_hardened_consensus=True,
            legacy_fallback_on_fail_safe=False,
            quorum_threshold=2,
        )
        engine_quorum = ConsensusEngine(quorum_config)
        success = MagicMock(
            vote=AsyncMock(
                return_value=VoteOutput(
                    persona_type=PersonaType.MELCHIOR,
                    vote=Vote.APPROVE,
                    reason="ok",
                )
            )
        )
        failure = MagicMock(vote=AsyncMock(side_effect=Exception("vote failed")))
        with patch.object(
            engine_quorum, "_create_agents", return_value={
                PersonaType.MELCHIOR: success,
                PersonaType.BALTHASAR: failure,
            }
        ), patch.object(
            engine_quorum, "_build_voting_context", return_value="ctx"
        ):
            _ = await engine_quorum._run_voting_phase({}, [])

        quorum_event = next(
            evt for evt in engine_quorum.events if evt["type"] == "quorum.fail_safe"
        )
        self.assertEqual(
            quorum_event["code"], ErrorCode.CONSENSUS_QUORUM_UNSATISFIED.value
        )
        self.assertEqual(quorum_event["phase"], "voting")


class TestStreamingMetrics(unittest.IsolatedAsyncioTestCase):
    """簡易パフォーマンステストとしてストリーミング指標を計測する."""

    async def test_streaming_metrics_capture_ttfb_and_elapsed(self) -> None:
        """TTFB と経過時間がストリーミング状態に記録される."""
        config = Config(
            api_key="key",
            debate_rounds=1,
            enable_streaming_output=True,
            streaming_queue_size=4,
            streaming_emit_timeout_seconds=0.5,
            token_budget=256,
        )
        emitter = RecordingEmitter(emit_delay=0.01)
        engine = ConsensusEngine(config, streaming_emitter=emitter)

        outputs = {
            PersonaType.MELCHIOR: DebateOutput(
                persona_type=PersonaType.MELCHIOR,
                round_number=1,
                responses={PersonaType.BALTHASAR: "a" * 10},
                timestamp=datetime.now(),
            ),
            PersonaType.BALTHASAR: DebateOutput(
                persona_type=PersonaType.BALTHASAR,
                round_number=1,
                responses={PersonaType.MELCHIOR: "b" * 10},
                timestamp=datetime.now(),
            ),
        }
        agents = {
            persona: MagicMock(debate=AsyncMock(return_value=output))
            for persona, output in outputs.items()
        }
        thinking = {
            PersonaType.MELCHIOR: ThinkingOutput(
                persona_type=PersonaType.MELCHIOR,
                content="m",
                timestamp=datetime.now(),
            ),
            PersonaType.BALTHASAR: ThinkingOutput(
                persona_type=PersonaType.BALTHASAR,
                content="b",
                timestamp=datetime.now(),
            ),
        }

        with patch.object(engine, "_create_agents", return_value=agents):
            await engine._run_debate_phase(thinking)

        state = engine.streaming_state
        self.assertTrue(state["enabled"])
        self.assertGreater(state["emitted"], 0)
        self.assertIsNotNone(state.get("ttfb_ms"))
        self.assertIsNotNone(state.get("elapsed_ms"))
        self.assertGreaterEqual(state["elapsed_ms"], state["ttfb_ms"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
