"""LLM 同時実行数を制御する ConcurrencyController."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class ConcurrencyLimitError(Exception):
    """セマフォ取得がタイムアウトした場合のエラー."""


@dataclass(frozen=True)
class ConcurrencyMetrics:
    """同時実行制御のメトリクス."""

    active_count: int
    waiting_count: int
    total_acquired: int
    total_timeouts: int
    total_rate_limits: int


class ConcurrencyController:
    """asyncio.Semaphore で LLM 同時実行数を管理する."""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent は 1 以上である必要があります")

        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
        self._waiting_count = 0
        self._total_acquired = 0
        self._total_timeouts = 0
        self._total_rate_limits = 0

    @asynccontextmanager
    async def acquire(self, timeout: Optional[float] = None) -> AsyncGenerator[None, None]:
        """同時実行許可を取得するコンテキストマネージャ."""
        self._waiting_count += 1
        try:
            if timeout is None:
                await self._semaphore.acquire()
            else:
                try:
                    await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
                except asyncio.TimeoutError as exc:
                    self._total_timeouts += 1
                    raise ConcurrencyLimitError(
                        f"Semaphore acquire timed out after {timeout} seconds"
                    ) from exc
        finally:
            # タイムアウト時も取得成功時も待機カウンタを戻す
            self._waiting_count = max(0, self._waiting_count - 1)

        self._active_count += 1
        self._total_acquired += 1
        try:
            yield
        finally:
            self._active_count = max(0, self._active_count - 1)
            self._semaphore.release()

    def get_metrics(self) -> ConcurrencyMetrics:
        """現在のメトリクスを取得する."""
        return ConcurrencyMetrics(
            active_count=self._active_count,
            waiting_count=self._waiting_count,
            total_acquired=self._total_acquired,
            total_timeouts=self._total_timeouts,
            total_rate_limits=self._total_rate_limits,
        )

    def note_rate_limit(self) -> None:
        """レート制限発生を記録する."""
        self._total_rate_limits += 1
