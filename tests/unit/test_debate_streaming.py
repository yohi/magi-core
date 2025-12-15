"""Debate ストリーミングのユニットテスト."""

import asyncio
from datetime import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.core.streaming import QueueStreamingEmitter, StreamingTimeoutError
from magi.models import DebateOutput, PersonaType, ThinkingOutput


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
        self.assertEqual("overflow", events[0][1]["reason"])
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
        self.assertEqual("streaming.timeout", events[0][0])
        self.assertEqual("backpressure_timeout", events[0][1]["reason"])


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
