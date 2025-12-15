"""ストリーミング送出を管理するユーティリティ."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """ストリーミングで送出するチャンク."""

    persona: str
    chunk: str
    phase: str
    round_number: Optional[int] = None
    priority: Literal["normal", "critical"] = "normal"


class StreamingTimeoutError(TimeoutError):
    """バックプレッシャモードでのキュー空き待ちタイムアウト."""


class BaseStreamingEmitter:
    """ストリーミング送出のベースクラス."""

    async def start(self) -> "BaseStreamingEmitter":  # pragma: no cover - インターフェース
        return self

    async def emit(
        self,
        persona: str,
        chunk: str,
        phase: str,
        round_number: Optional[int] = None,
        priority: Literal["normal", "critical"] = "normal",
    ) -> None:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - インターフェース
        return None

    @property
    def dropped(self) -> int:
        """ドロップしたチャンク数."""
        return 0


class NullStreamingEmitter(BaseStreamingEmitter):
    """ストリーミングを無効化するノップエミッタ."""

    async def emit(
        self,
        persona: str,
        chunk: str,
        phase: str,
        round_number: Optional[int] = None,
        priority: Literal["normal", "critical"] = "normal",
    ) -> None:
        return None


class QueueStreamingEmitter(BaseStreamingEmitter):
    """キューで送出を制御するストリーミングエミッタ."""

    def __init__(
        self,
        send_func: Callable[[StreamChunk], Awaitable[None]],
        queue_size: int = 100,
        emit_timeout_seconds: float = 2.0,
        auto_start: bool = True,
        overflow_policy: Literal["drop", "backpressure"] = "drop",
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._send_func = send_func
        self._queue: asyncio.Queue[StreamChunk] = asyncio.Queue(maxsize=queue_size)
        self._emit_timeout = emit_timeout_seconds
        self._worker: asyncio.Task | None = None
        self._closed = False
        self._dropped = 0
        self._auto_start = auto_start
        self._overflow_policy = overflow_policy
        self._on_event = on_event

    async def start(self) -> "QueueStreamingEmitter":
        if self._worker is None:
            self._worker = asyncio.create_task(self._drain())
        return self

    async def emit(
        self,
        persona: str,
        chunk: str,
        phase: str,
        round_number: Optional[int] = None,
        priority: Literal["normal", "critical"] = "normal",
    ) -> None:
        if self._closed:
            return None

        if self._auto_start:
            await self.start()
        stream_chunk = StreamChunk(
            persona=persona,
            chunk=chunk,
            phase=phase,
            round_number=round_number,
            priority=priority,
        )

        if self._queue.full():
            if self._overflow_policy == "drop":
                await self._handle_drop_policy(stream_chunk)
                return None
            await self._handle_backpressure_policy(stream_chunk)
            return None

        self._queue.put_nowait(stream_chunk)
        return None

    def _emit_event(self, event_type: str, **payload: object) -> None:
        if self._on_event is None:
            return
        self._on_event(
            event_type,
            {
                **payload,
                "queue_size": self._queue.maxsize,
                "queue_length": self._queue.qsize(),
            },
        )

    def _log_timeout(self, stream_chunk: StreamChunk, reason: str) -> None:
        logger.warning(
            "streaming.emitter.timeout persona=%s phase=%s round=%s priority=%s "
            "dropped_total=%s reason=%s queue_length=%s queue_size=%s",
            stream_chunk.persona,
            stream_chunk.phase,
            stream_chunk.round_number,
            stream_chunk.priority,
            self._dropped,
            reason,
            self._queue.qsize(),
            self._queue.maxsize,
        )
        self._emit_event(
            "streaming.timeout",
            persona=stream_chunk.persona,
            phase=stream_chunk.phase,
            round=stream_chunk.round_number,
            priority=stream_chunk.priority,
            dropped_total=self._dropped,
            reason=reason,
        )

    def _log_drop(
        self, stream_chunk: StreamChunk, dropped_persona: str, reason: str
    ) -> None:
        self._dropped += 1
        logger.warning(
            "streaming.emitter.drop persona=%s phase=%s round=%s dropped_persona=%s "
            "dropped_total=%s reason=%s queue_length=%s queue_size=%s",
            stream_chunk.persona,
            stream_chunk.phase,
            stream_chunk.round_number,
            dropped_persona,
            self._dropped,
            reason,
            self._queue.qsize(),
            self._queue.maxsize,
        )
        self._emit_event(
            "streaming.drop",
            persona=stream_chunk.persona,
            phase=stream_chunk.phase,
            round=stream_chunk.round_number,
            priority=stream_chunk.priority,
            dropped_persona=dropped_persona,
            dropped_total=self._dropped,
            reason=reason,
        )

    def _evict_oldest_non_critical(self) -> Optional[StreamChunk]:
        """最古の非クリティカルチャンクをドロップする."""
        for idx, existing in enumerate(self._queue._queue):  # type: ignore[attr-defined]
            if existing.priority != "critical":
                dropped = self._queue._queue[idx]  # type: ignore[attr-defined]
                del self._queue._queue[idx]  # type: ignore[attr-defined]
                if hasattr(self._queue, "_unfinished_tasks"):
                    self._queue._unfinished_tasks = max(  # type: ignore[attr-defined]
                        0, self._queue._unfinished_tasks - 1  # type: ignore[attr-defined]
                    )
                return dropped
        return None

    async def _handle_drop_policy(self, stream_chunk: StreamChunk) -> None:
        dropped = self._evict_oldest_non_critical()
        if dropped is None:
            if stream_chunk.priority == "critical":
                try:
                    await asyncio.wait_for(
                        self._queue.put(stream_chunk),
                        timeout=self._emit_timeout,
                    )
                except asyncio.TimeoutError:
                    self._log_timeout(stream_chunk, reason="drop_policy_timeout")
                return None

            self._log_drop(stream_chunk, stream_chunk.persona, reason="overflow")
            return None

        self._log_drop(stream_chunk, dropped.persona, reason="evicted")
        try:
            self._queue.put_nowait(stream_chunk)
        except asyncio.QueueFull:
            # フォールバックで空きを待つ（理論上ここには到達しない）
            await self._queue.put(stream_chunk)

    async def _handle_backpressure_policy(self, stream_chunk: StreamChunk) -> None:
        try:
            await asyncio.wait_for(
                self._queue.put(stream_chunk),
                timeout=self._emit_timeout,
            )
        except asyncio.TimeoutError:
            if stream_chunk.priority == "critical":
                dropped = self._evict_oldest_non_critical()
                if dropped is not None:
                    self._log_drop(stream_chunk, dropped.persona, reason="evicted")
                    self._queue.put_nowait(stream_chunk)
                    return None
                self._log_timeout(stream_chunk, reason="backpressure_timeout")
                return None

            self._log_drop(stream_chunk, stream_chunk.persona, reason="backpressure_timeout")
            raise StreamingTimeoutError(
                f"streaming queue is full (policy=backpressure) "
                f"for persona={stream_chunk.persona}"
            )

    async def _drain(self) -> None:
        while not self._closed:
            try:
                chunk = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                await asyncio.wait_for(
                    self._send_func(chunk),
                    timeout=self._emit_timeout,
                )
            except asyncio.TimeoutError:
                self._log_timeout(chunk, reason="emit_timeout")
            except Exception as exc:  # pragma: no cover - エラーログのみ
                logger.warning(
                    "streaming.emitter.error persona=%s phase=%s round=%s error=%s",
                    chunk.persona,
                    chunk.phase,
                    chunk.round_number,
                    exc,
                )
            finally:
                self._queue.task_done()

        # キャンセル時も残タスクを掃除する
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def aclose(self) -> None:
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        return None

    @property
    def dropped(self) -> int:
        return self._dropped
