"""Debate ストリーミングのユニットテスト."""

import asyncio
from datetime import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.core.streaming import (
    QueueStreamingEmitter,
    StreamingState,
    StreamingTimeoutError,
)
from magi.models import (
    ConsensusPhase,
    DebateOutput,
    Decision,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
)


class RecordingEmitter:
    """テスト用のシンプルなストリーミングエミッタ."""

    def __init__(self) -> None:
        self.chunks = []
        self.started = False
        self.closed = False
        self.dropped = 0

    async def start(self) -> "RecordingEmitter":
        self.started = True
        return self

    async def emit(
        self,
        persona: str,
        chunk: str,
        phase: str,
        round_number: int | None = None,
        priority: str = "normal",
    ) -> None:
        self.chunks.append((persona, chunk, phase, round_number, priority))

    async def aclose(self) -> None:
        self.closed = True


class TestQueueStreamingEmitter(unittest.IsolatedAsyncioTestCase):
    """QueueStreamingEmitter の挙動を検証する."""

    async def test_drop_records_event_and_counts(self) -> None:
        """ドロップ時にイベントと欠落件数が記録される."""
        events = []
        gate = asyncio.Event()

        async def slow_send(_chunk):
            await gate.wait()

        def on_event(event_type: str, payload: dict) -> None:
            events.append((event_type, payload))

        emitter = QueueStreamingEmitter(
            send_func=slow_send,
            queue_size=1,
            emit_timeout_seconds=0.05,
            auto_start=False,
            on_event=on_event,
        )
        await emitter.emit("melchior", "c1", "debate", 1)
        with self.assertLogs("magi.core.streaming", level="WARNING") as captured:
            await emitter.emit("balthasar", "c2", "debate", 1)
        gate.set()
        await emitter.aclose()

        self.assertEqual(1, emitter.dropped)
        self.assertEqual("streaming.drop", events[0][0])
        self.assertEqual(1, events[0][1]["dropped_total"])
        self.assertEqual("evicted", events[0][1]["reason"])
        self.assertTrue(any("dropped_total=1" in msg for msg in captured.output))

    async def test_drop_oldest_when_queue_full(self) -> None:
        """キュー満杯時に最古のチャンクをドロップして最新を保持する."""
        sent = []
        gate = asyncio.Event()

        async def slow_send(chunk):
            await gate.wait()
            sent.append(chunk)

        emitter = QueueStreamingEmitter(
            send_func=slow_send,
            queue_size=2,
            emit_timeout_seconds=0.2,
            auto_start=False,
        )
        with self.assertLogs("magi.core.streaming", level="WARNING") as captured:
            await emitter.emit("melchior", "c1", "debate", 1)
            await emitter.emit("balthasar", "c2", "debate", 1)
            await emitter.emit("casper", "c3", "debate", 1)
            await emitter.start()
            gate.set()
            await asyncio.sleep(0.05)
        await emitter.aclose()

        self.assertEqual(["c2", "c3"], [c.chunk for c in sent])
        self.assertTrue(any("drop" in msg for msg in captured.output))

    async def test_emit_timeout_records_warning(self) -> None:
        """送出がタイムアウトした場合に警告ログを記録する."""

        async def slow_send(_chunk):
            await asyncio.sleep(0.05)

        emitter = QueueStreamingEmitter(
            send_func=slow_send,
            queue_size=1,
            emit_timeout_seconds=0.01,
        )
        await emitter.start()
        with self.assertLogs("magi.core.streaming", level="WARNING") as captured:
            await emitter.emit("melchior", "c1", "debate", 1)
            await asyncio.sleep(0.02)
        await emitter.aclose()

        self.assertTrue(any("timeout" in msg for msg in captured.output))

    async def test_drop_mode_prefers_critical_event(self) -> None:
        """drop モードでは非クリティカルを優先的にドロップしクリティカルを保持する."""
        sent = []
        gate = asyncio.Event()

        async def slow_send(chunk):
            await gate.wait()
            sent.append(chunk)

        emitter = QueueStreamingEmitter(
            send_func=slow_send,
            queue_size=1,
            emit_timeout_seconds=0.2,
            auto_start=False,
        )
        # 先に通常イベントで満杯にする
        await emitter.emit("melchior", "normal", "debate", 1, priority="normal")
        with self.assertLogs("magi.core.streaming", level="WARNING") as captured:
            await emitter.emit("balthasar", "critical", "debate", 1, priority="critical")
            await emitter.start()
            gate.set()
            await asyncio.sleep(0.05)
        await emitter.aclose()

        self.assertEqual(["critical"], [c.chunk for c in sent])
        self.assertEqual(1, emitter.dropped)
        self.assertTrue(any("drop" in msg for msg in captured.output))

    async def test_backpressure_timeout_raises_for_normal(self) -> None:
        """backpressure モードでは空き待ちタイムアウトで例外を送出する."""
        send = AsyncMock()
        events = []

        def on_event(event_type: str, payload: dict) -> None:
            events.append((event_type, payload))

        emitter = QueueStreamingEmitter(
            send_func=send,
            queue_size=1,
            emit_timeout_seconds=0.01,
            auto_start=False,
            overflow_policy="backpressure",
            on_event=on_event,
        )
        await emitter.emit("melchior", "c1", "debate", 1)
        with self.assertRaises(StreamingTimeoutError):
            await emitter.emit("balthasar", "c2", "debate", 1)
        await emitter.aclose()

        self.assertEqual(1, emitter.dropped)
        self.assertEqual("streaming.drop", events[0][0])
        self.assertEqual("backpressure_timeout", events[0][1]["reason"])

    async def test_get_state_reports_metrics(self) -> None:
        """get_state でキューメトリクスと TTFB/経過時間を取得できる."""
        gate = asyncio.Event()

        async def gated_send(_chunk):
            await gate.wait()

        emitter = QueueStreamingEmitter(
            send_func=gated_send,
            queue_size=2,
            emit_timeout_seconds=0.05,
            auto_start=False,
        )

        initial = emitter.get_state()
        self.assertIsInstance(initial, StreamingState)
        self.assertEqual(2, initial.queue_size)
        self.assertEqual(0, initial.emitted_count)
        self.assertIsNone(initial.ttfb_ms)

        await emitter.emit("melchior", "c1", "debate", 1)
        await emitter.start()
        gate.set()
        await asyncio.sleep(0.02)

        state = emitter.get_state()
        self.assertGreaterEqual(state.emitted_count, 1)
        self.assertEqual(0, state.dropped_count)
        self.assertAlmostEqual(0.0, state.drop_rate)
        self.assertIsNotNone(state.ttfb_ms)
        self.assertIsNotNone(state.elapsed_ms)
        await emitter.aclose()

    async def test_get_state_tracks_drop_rate_and_reason(self) -> None:
        """ドロップ率と最終ドロップ理由を集計する."""

        async def immediate_send(_chunk):
            return None

        emitter = QueueStreamingEmitter(
            send_func=immediate_send,
            queue_size=1,
            emit_timeout_seconds=0.05,
            auto_start=False,
        )

        await emitter.emit("melchior", "c1", "debate", 1)
        await emitter.emit("balthasar", "c2", "debate", 1)
        await emitter.start()
        await asyncio.sleep(0.02)

        state = emitter.get_state()
        self.assertEqual(1, state.dropped_count)
        self.assertEqual("evicted", state.last_drop_reason)
        self.assertAlmostEqual(0.5, state.drop_rate)
        await emitter.aclose()


class TestConsensusDebateStreaming(unittest.IsolatedAsyncioTestCase):
    """ConsensusEngine の Debate ストリーミング連携を検証する."""

    def _thinking_results(self):
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
            PersonaType.CASPER: ThinkingOutput(
                persona_type=PersonaType.CASPER,
                content="c",
                timestamp=now,
            ),
        }

    async def test_streaming_disabled_keeps_bulk_flow(self) -> None:
        """ストリーミング無効時は従来の一括処理が維持される."""
        config = Config(api_key="key", debate_rounds=1, enable_streaming_output=False)
        engine = ConsensusEngine(config)
        outputs = {
            PersonaType.MELCHIOR: DebateOutput(
                persona_type=PersonaType.MELCHIOR,
                round_number=1,
                responses={PersonaType.BALTHASAR: "ok"},
                timestamp=datetime.now(),
            ),
            PersonaType.BALTHASAR: DebateOutput(
                persona_type=PersonaType.BALTHASAR,
                round_number=1,
                responses={PersonaType.MELCHIOR: "ok"},
                timestamp=datetime.now(),
            ),
            PersonaType.CASPER: DebateOutput(
                persona_type=PersonaType.CASPER,
                round_number=1,
                responses={PersonaType.MELCHIOR: "ok"},
                timestamp=datetime.now(),
            ),
        }
        agents = {
            persona: MagicMock(debate=AsyncMock(return_value=output))
            for persona, output in outputs.items()
        }

        with patch.object(engine, "_create_agents", return_value=agents):
            rounds = await engine._run_debate_phase(self._thinking_results())

        self.assertEqual(1, len(rounds))
        self.assertFalse(engine.streaming_state["fail_safe"])

    async def test_streaming_budget_abort_records_event(self) -> None:
        """トークン予算超過でストリーミングを中断しイベントを記録する."""
        config = Config(
            api_key="key",
            debate_rounds=1,
            enable_streaming_output=True,
            token_budget=5,
            streaming_queue_size=10,
        )
        emitter = RecordingEmitter()
        engine = ConsensusEngine(config, streaming_emitter=emitter)

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
            PersonaType.CASPER: DebateOutput(
                persona_type=PersonaType.CASPER,
                round_number=1,
                responses={PersonaType.MELCHIOR: long_text},
                timestamp=datetime.now(),
            ),
        }
        agents = {
            persona: MagicMock(debate=AsyncMock(return_value=output))
            for persona, output in outputs.items()
        }

        with patch.object(engine, "_create_agents", return_value=agents):
            rounds = await engine._run_debate_phase(self._thinking_results())

        self.assertLessEqual(len(rounds), 1)
        self.assertTrue(engine.streaming_state["fail_safe"])
        self.assertTrue(
            any(evt["type"] == "debate.streaming.aborted" for evt in engine.events)
        )
        self.assertGreaterEqual(len(emitter.chunks), 1)


class TestConsensusStreamingIntegration(unittest.IsolatedAsyncioTestCase):
    """ConsensusEngine のストリーミング統合を検証する."""

    def setUp(self) -> None:
        self.config = Config(api_key="key", enable_streaming_output=True)
        self.emitter = RecordingEmitter()
        self.engine = ConsensusEngine(self.config, streaming_emitter=self.emitter)

    async def test_thinking_phase_streams_each_persona(self) -> None:
        """Thinking フェーズで各ペルソナの出力がストリーム送出される."""
        now = datetime.now()
        agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(
                    return_value=ThinkingOutput(
                        persona_type=PersonaType.MELCHIOR,
                        content="m-think",
                        timestamp=now,
                    )
                )
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(
                    return_value=ThinkingOutput(
                        persona_type=PersonaType.BALTHASAR,
                        content="b-think",
                        timestamp=now,
                    )
                )
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(
                    return_value=ThinkingOutput(
                        persona_type=PersonaType.CASPER,
                        content="c-think",
                        timestamp=now,
                    )
                )
            ),
        }

        with patch.object(self.engine, "_create_agents", return_value=agents):
            await self.engine._run_thinking_phase("prompt")

        thinking_chunks = [
            chunk for chunk in self.emitter.chunks
            if chunk[2] == ConsensusPhase.THINKING.value
        ]
        self.assertEqual(3, len(thinking_chunks))
        self.assertEqual(
            {PersonaType.MELCHIOR.value, PersonaType.BALTHASAR.value, PersonaType.CASPER.value},
            {chunk[0] for chunk in thinking_chunks},
        )
        self.assertTrue(all(chunk[4] == "normal" for chunk in thinking_chunks))

    async def test_voting_phase_streams_votes_and_final_result(self) -> None:
        """Voting フェーズと最終結果がストリーム送出される."""

        class StubStrategy:
            name = "stub"

            async def run(self, _thinking, _debate):
                return {
                    "voting_results": {
                        PersonaType.MELCHIOR: VoteOutput(
                            persona_type=PersonaType.MELCHIOR,
                            vote=Vote.APPROVE,
                            reason="ok",
                            conditions=[],
                        ),
                        PersonaType.BALTHASAR: VoteOutput(
                            persona_type=PersonaType.BALTHASAR,
                            vote=Vote.DENY,
                            reason="reject",
                            conditions=[],
                        ),
                    },
                    "decision": Decision.APPROVED,
                    "exit_code": 0,
                    "all_conditions": ["c1"],
                }

        with patch.object(self.engine, "_select_voting_strategy", return_value=StubStrategy()):
            result = await self.engine._run_voting_phase({}, [])

        self.assertEqual(Decision.APPROVED, result["decision"])
        voting_chunks = [
            chunk for chunk in self.emitter.chunks
            if chunk[2] == ConsensusPhase.VOTING.value
        ]
        self.assertEqual(2, len(voting_chunks))
        self.assertEqual(
            {PersonaType.MELCHIOR.value, PersonaType.BALTHASAR.value},
            {chunk[0] for chunk in voting_chunks},
        )

        final_chunks = [
            chunk for chunk in self.emitter.chunks
            if chunk[2] == ConsensusPhase.COMPLETED.value
        ]
        self.assertEqual(1, len(final_chunks))
        self.assertEqual("critical", final_chunks[0][4])
        self.assertIn("approved", final_chunks[0][1])
