"""
SessionManagerの実装
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, Any

from magi.webui_backend.models import (
    Session,
    SessionOptions,
    SessionPhase,
    UnitType,
    UnitState,
)
from magi.webui_backend.adapter import MagiAdapter, MockMagiAdapter
from magi.webui_backend.broadcaster import EventBroadcaster

logger = logging.getLogger(__name__)

class SessionManager:
    """
    セッションのライフサイクル、状態、同時実行数を管理するクラス。
    """

    def __init__(
        self,
        max_concurrency: int = 10,
        ttl_sec: int = 600,
        adapter_factory: Optional[Callable[[], MagiAdapter]] = None,
        broadcaster: Optional[EventBroadcaster] = None,
    ):
        self.max_concurrency = max_concurrency
        self.ttl_sec = ttl_sec
        self.sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()
        
        self.adapter_factory = adapter_factory or (lambda: MockMagiAdapter())
        self.broadcaster = broadcaster or EventBroadcaster()

    async def create_session(self, prompt: str, options: Optional[SessionOptions] = None) -> str:
        """
        新規セッションを作成し、実行を開始する。

        Raises:
            RuntimeError: 同時実行数が上限に達している場合
        """
        if options is None:
            options = SessionOptions()

        async with self._lock:
            # 期限切れセッションの掃除（opportunistic cleanup）
            self._cleanup_expired_sessions_unsafe()

            if len(self.sessions) >= self.max_concurrency:
                raise RuntimeError("Max concurrency limit reached")

            session = Session(prompt=prompt, options=options)
            self.sessions[session.session_id] = session
            
            # バックグラウンドタスクとして実行開始
            # run_session は非同期で実行され、セッション状態を更新していく
            task = asyncio.create_task(self._run_session_task(session.session_id))
            session.set_task(task)
            
            logger.info(f"Session created: {session.session_id}")
            return session.session_id

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        セッションを取得し、最終アクセス時刻を更新する。
        """
        session = self.sessions.get(session_id)
        if session:
            session.touch()
        return session

    async def cancel_session(self, session_id: str) -> bool:
        """
        セッションをキャンセルする。
        実行中のタスクがあればキャンセルし、ステータスを更新する。
        """
        async with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False

            if session.phase in [SessionPhase.RESOLVED, SessionPhase.CANCELLED, SessionPhase.ERROR]:
                return True  # 既に終了状態

            # タスクのキャンセル
            task = session.get_task()
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            session.phase = SessionPhase.CANCELLED
            session.logs.append("Session cancelled by user.")
            logger.info(f"Session cancelled: {session_id}")
            return True

    def _cleanup_expired_sessions_unsafe(self):
        """
        期限切れセッションを削除する（ロック内から呼ぶこと）。
        """
        now = datetime.now()
        expired_ids = []
        for sid, session in self.sessions.items():
            # 最終アクセスからTTL経過したら削除
            # (実行中でも削除するかは要件次第だが、通常はアクセスがなければ放置セッションとみなす)
            # ただし実行中は last_accessed を更新する仕組みがないと消えるリスクがある。
            # 今回は簡易的に「終了状態かつTTL経過」または「TTL経過(強制)」とするが、
            # 仕様「TTLで期限切れセッションが掃除される」に従い、アクセスベースで判定する。
            if (now - session.last_accessed_at) > timedelta(seconds=self.ttl_sec):
                expired_ids.append(sid)
        
        for sid in expired_ids:
            # タスクが生きていればキャンセル
            task = self.sessions[sid].get_task()
            if task and not task.done():
                task.cancel()
            del self.sessions[sid]
            logger.info(f"Session expired and removed: {sid}")

    async def _run_session_task(self, session_id: str):
        """
        セッション実行の実体（ラッパー）。
        エラーハンドリングと状態遷移を行う。
        """
        session = self.sessions.get(session_id)
        if not session:
            return

        try:
            adapter = self.adapter_factory()
            
            async for event in adapter.run(session.prompt, session.options):
                self._update_session_state(session, event)
                await self.broadcaster.publish(session_id, event)

        except asyncio.CancelledError:
            session.phase = SessionPhase.CANCELLED
            session.logs.append("Task cancelled.")
            await self.broadcaster.publish(session_id, {
                "type": "phase",
                "phase": SessionPhase.CANCELLED.value
            })
        except Exception as e:
            session.phase = SessionPhase.ERROR
            msg = f"Internal Error: {str(e)}"
            session.logs.append(msg)
            logger.exception(f"Error in session {session_id}")
            await self.broadcaster.publish(session_id, {
                "type": "error",
                "message": msg
            })

    def _update_session_state(self, session: Session, event: Dict[str, Any]):
        """
        イベントに基づいてセッション状態を更新する。
        """
        event_type = event.get("type")
        
        if event_type == "phase":
            phase_val = event.get("phase")
            try:
                if phase_val:
                    session.phase = SessionPhase(phase_val)
            except ValueError:
                logger.warning(f"Unknown phase: {phase_val}")

        elif event_type == "progress":
            pct = event.get("pct")
            if isinstance(pct, (int, float)):
                session.progress = int(pct)

        elif event_type == "log":
            lines = event.get("lines", [])
            if isinstance(lines, list):
                session.logs.extend([str(l) for l in lines])
                if len(session.logs) > 200:
                    session.logs = session.logs[-200:]

        elif event_type == "unit":
            unit_val = event.get("unit")
            try:
                unit_type = UnitType(unit_val)
                if unit_type in session.units:
                    unit_status = session.units[unit_type]
                    if "state" in event:
                        unit_status.state = UnitState(event["state"])
                    if "message" in event:
                        unit_status.message = str(event["message"])
                    if "score" in event:
                        unit_status.score = float(event["score"])
            except ValueError:
                pass

        elif event_type == "final":
            session.phase = SessionPhase.RESOLVED
            session.progress = 100
            decision = event.get("decision", "UNKNOWN")
            session.logs.append(f"Session Resolved: {decision}")

        elif event_type == "error":
            session.phase = SessionPhase.ERROR
            msg = event.get("message", "Unknown error")
            session.logs.append(f"Error received: {msg}")
