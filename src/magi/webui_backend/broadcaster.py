"""
EventBroadcasterの実装

WebUIへのイベント配信を行うブロードキャスター。
セッションごとのPub/Sub管理、共通フィールドの付与、およびバックプレッシャー制御を行う。
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class EventBroadcaster:
    """イベントブロードキャスター"""

    def __init__(self, queue_maxsize: int = 100):
        """
        Args:
            queue_maxsize (int): 購読者ごとのキューの最大サイズ。これを超えると古いイベントから破棄される。
        """
        # session_id -> List[asyncio.Queue]
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._queue_maxsize = queue_maxsize

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """
        セッションのイベントを購読するためのキューを取得する。
        
        Args:
            session_id (str): セッションID

        Returns:
            asyncio.Queue: イベントが配信されるキュー
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            self._subscribers[session_id].append(queue)
        
        logger.debug(f"New subscriber for session {session_id}")
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        """
        購読を解除する。

        Args:
            session_id (str): セッションID
            queue (asyncio.Queue): 解除するキュー
        """
        async with self._lock:
            if session_id in self._subscribers:
                if queue in self._subscribers[session_id]:
                    self._subscribers[session_id].remove(queue)
                
                # リストが空になったらエントリを削除
                if not self._subscribers[session_id]:
                    del self._subscribers[session_id]
        
        logger.debug(f"Unsubscribed from session {session_id}")

    async def publish(self, session_id: str, payload: Dict[str, Any]) -> None:
        """
        セッションに対してイベントを配信する。
        共通フィールド (schema_version, session_id, ts) が自動的に付与される。
        バックプレッシャー制御として、キューが満杯の場合は古いイベントを破棄する。

        Args:
            session_id (str): セッションID
            payload (Dict[str, Any]): イベントペイロード
        """
        # 共通フィールドの付与
        event = payload.copy()
        event.update({
            "schema_version": "1.0",
            "session_id": session_id,
            "ts": datetime.now(timezone.utc).isoformat()
        })

        async with self._lock:
            queues = self._subscribers.get(session_id, [])
            # リストのコピーを作成して反復処理中の変更を防ぐ（基本的にはunsubscribeはlockで守られているが念のため）
            target_queues = list(queues)

        if not target_queues:
            return

        for q in target_queues:
            try:
                # ノンブロッキングでputを試みる
                q.put_nowait(event)
            except asyncio.QueueFull:
                # キューが満杯の場合、古いイベントを捨てて新しいイベントを入れる (Drop-Oldest)
                try:
                    _ = q.get_nowait()
                    q.put_nowait(event)
                    logger.debug(f"Queue full for session {session_id}, dropped oldest event.")
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # 競合状態でここに来る可能性は低いが、エラーハンドリング
                    pass
