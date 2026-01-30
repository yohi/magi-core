"""
EventBroadcasterのユニットテスト
"""
import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from magi.webui_backend.broadcaster import EventBroadcaster

class TestEventBroadcaster(unittest.TestCase):
    """EventBroadcasterのテストケース"""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.broadcaster = EventBroadcaster(queue_maxsize=3)

    def tearDown(self):
        self.loop.close()

    def test_subscribe_publish_receive(self):
        """正常系: 購読、配信、受信の確認"""
        async def _test():
            session_id = "sess-1"
            queue = await self.broadcaster.subscribe(session_id)
            
            payload = {"type": "log", "message": "hello"}
            await self.broadcaster.publish(session_id, payload)
            
            received = await queue.get()
            
            # ペイロードの内容確認
            self.assertEqual(received["type"], "log")
            self.assertEqual(received["message"], "hello")
            
            # 共通フィールドの確認
            self.assertEqual(received["schema_version"], "1.0")
            self.assertEqual(received["session_id"], session_id)
            self.assertTrue("ts" in received)
            # ISOフォーマットの日時か確認
            try:
                datetime.fromisoformat(received["ts"])
            except ValueError:
                self.fail("ts field is not a valid ISO format")

        self.loop.run_until_complete(_test())

    def test_multiple_subscribers(self):
        """正常系: 複数購読者への配信確認"""
        async def _test():
            session_id = "sess-1"
            q1 = await self.broadcaster.subscribe(session_id)
            q2 = await self.broadcaster.subscribe(session_id)
            
            payload = {"type": "test"}
            await self.broadcaster.publish(session_id, payload)
            
            res1 = await q1.get()
            res2 = await q2.get()
            
            self.assertEqual(res1["type"], "test")
            self.assertEqual(res2["type"], "test")
            
            # 別セッションには配信されないこと
            other_sess = "sess-2"
            q3 = await self.broadcaster.subscribe(other_sess)
            await self.broadcaster.publish(session_id, {"type": "test2"})
            
            self.assertTrue(q3.empty())

        self.loop.run_until_complete(_test())

    def test_unsubscribe(self):
        """正常系: 購読解除の確認"""
        async def _test():
            session_id = "sess-1"
            q1 = await self.broadcaster.subscribe(session_id)
            
            # 購読解除
            await self.broadcaster.unsubscribe(session_id, q1)
            
            # 配信
            await self.broadcaster.publish(session_id, {"type": "test"})
            
            # キューは空のまま
            self.assertTrue(q1.empty())

        self.loop.run_until_complete(_test())

    def test_backpressure_drop_oldest(self):
        """準正常系: バックプレッシャー（古いイベントの間引き）確認"""
        async def _test():
            # maxsize=3 で初期化されている
            session_id = "sess-bp"
            queue = await self.broadcaster.subscribe(session_id)
            
            # 3つ送る (満杯にする)
            for i in range(3):
                await self.broadcaster.publish(session_id, {"seq": i})
            
            self.assertTrue(queue.full())
            
            # 4つ目を送る -> seq=0 が捨てられ、seq=1, 2, 3 になるはず
            await self.broadcaster.publish(session_id, {"seq": 3})
            
            # 取り出して確認
            item1 = await queue.get()
            self.assertEqual(item1["seq"], 1) # seq=0 は捨てられた
            
            item2 = await queue.get()
            self.assertEqual(item2["seq"], 2)
            
            item3 = await queue.get()
            self.assertEqual(item3["seq"], 3)
            
            self.assertTrue(queue.empty())

        self.loop.run_until_complete(_test())
