"""ストリーミング送出を管理するユーティリティ."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """ストリーミングで送出するチャンク."""

    persona: str
    chunk: str
    phase: str
    round_number: Optional[int] = None


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
    ) -> None:
        self._send_func = send_func
        self._queue: asyncio.Queue[StreamChunk] = asyncio.Queue(maxsize=queue_size)
        self._emit_timeout = emit_timeout_seconds
        self._worker: asyncio.Task | None = None
        self._closed = False
        self._dropped = 0
        self._auto_start = auto_start

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
        )

        if self._queue.full():
            dropped: StreamChunk | None = None
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                dropped = None
            self._dropped += 1
            logger.warning(
                "streaming.emitter.drop persona=%s phase=%s round=%s dropped_persona=%s",
                persona,
                phase,
                round_number,
                dropped.persona if dropped else None,
            )

        try:
            self._queue.put_nowait(stream_chunk)
        except asyncio.QueueFull:
            self._dropped += 1
            logger.warning(
                "streaming.emitter.drop persona=%s phase=%s round=%s dropped_persona=%s",
                persona,
                phase,
                round_number,
                stream_chunk.persona,
            )

        return None

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
                logger.warning(
                    "streaming.emitter.timeout persona=%s phase=%s round=%s",
                    chunk.persona,
                    chunk.phase,
                    chunk.round_number,
                )
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
