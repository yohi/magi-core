"""ConcurrencyController のユニットテスト."""

import asyncio
import unittest

from magi.core.concurrency import (
    ConcurrencyController,
    ConcurrencyLimitError,
)


class TestConcurrencyController(unittest.IsolatedAsyncioTestCase):
    """ConcurrencyController の基本動作を検証する."""

    async def test_acquire_respects_limit_and_tracks_waiting(self) -> None:
        """上限超過時は待機し、メトリクスが更新される."""
        controller = ConcurrencyController(max_concurrent=1)
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def first_worker() -> None:
            async with controller.acquire():
                first_started.set()
                await release_first.wait()

        first_task = asyncio.create_task(first_worker())
        await first_started.wait()

        self.assertEqual(controller.get_metrics().active_count, 1)

        second_acquired = asyncio.Event()

        async def second_worker() -> None:
            async with controller.acquire(timeout=0.2):
                second_acquired.set()

        second_task = asyncio.create_task(second_worker())

        # second が待機状態に入るのを待つ
        await asyncio.sleep(0.05)
        waiting_metrics = controller.get_metrics()
        self.assertEqual(waiting_metrics.active_count, 1)
        self.assertEqual(waiting_metrics.waiting_count, 1)

        # 1 つ目を解放すると 2 つ目が取得できる
        release_first.set()
        await second_acquired.wait()
        await first_task
        await second_task

        final_metrics = controller.get_metrics()
        self.assertEqual(final_metrics.active_count, 0)
        self.assertEqual(final_metrics.waiting_count, 0)
        self.assertEqual(final_metrics.total_acquired, 2)

    async def test_timeout_raises_and_increments_metric(self) -> None:
        """待機がタイムアウトすると ConcurrencyLimitError を送出する."""
        controller = ConcurrencyController(max_concurrent=1)
        holder_ready = asyncio.Event()
        release_holder = asyncio.Event()

        async def holder() -> None:
            async with controller.acquire():
                holder_ready.set()
                await release_holder.wait()

        holder_task = asyncio.create_task(holder())
        await holder_ready.wait()

        with self.assertRaises(ConcurrencyLimitError):
            async with controller.acquire(timeout=0.05):
                pass

        release_holder.set()
        await holder_task

        metrics = controller.get_metrics()
        self.assertEqual(metrics.total_timeouts, 1)
        self.assertEqual(metrics.active_count, 0)
        self.assertEqual(metrics.waiting_count, 0)

    async def test_note_rate_limit_records_metric(self) -> None:
        """レート制限記録がメトリクスに反映される."""
        controller = ConcurrencyController(max_concurrent=2)

        async with controller.acquire():
            controller.note_rate_limit()

        controller.note_rate_limit()

        metrics = controller.get_metrics()
        self.assertEqual(metrics.total_rate_limits, 2)
        self.assertEqual(metrics.total_acquired, 1)
        self.assertEqual(metrics.active_count, 0)
        self.assertEqual(metrics.waiting_count, 0)
