"""
WebUI Backend FastAPI Application

WebUIのバックエンドアプリケーションを提供する。
テストで使用されるFastAPIアプリケーションとセッションマネージャーを定義する。
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from magi.webui_backend.adapter import MagiAdapter, MockMagiAdapter
from magi.webui_backend.broadcaster import EventBroadcaster
from magi.webui_backend.models import SessionOptions

logger = logging.getLogger(__name__)

# FastAPIアプリケーションインスタンス
app = FastAPI(title="MAGI WebUI Backend", version="1.0.0")


class SessionCreateRequest(BaseModel):
    """セッション作成リクエスト"""
    prompt: str
    options: Optional[Dict[str, Any]] = None


class SessionCreateResponse(BaseModel):
    """セッション作成レスポンス"""
    session_id: str
    status: str


class SessionInfo:
    """セッション情報を保持するクラス"""
    def __init__(
        self,
        session_id: str,
        prompt: str,
        options: SessionOptions,
        adapter: MagiAdapter,
        broadcaster: EventBroadcaster
    ):
        self.session_id = session_id
        self.prompt = prompt
        self.options = options
        self.adapter = adapter
        self.broadcaster = broadcaster
        self.task: Optional[asyncio.Task] = None


class SessionManager:
    """セッション管理クラス"""
    def __init__(self):
        self.sessions: Dict[str, SessionInfo] = {}
    
    def create_session(
        self,
        prompt: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """新しいセッションを作成する"""
        session_id = str(uuid.uuid4())
        
        # オプションをSessionOptionsに変換
        session_options = SessionOptions(**(options or {}))
        
        # モックアダプターを使用（実際の実装では設定に応じて切り替え）
        adapter = MockMagiAdapter()
        
        # ブロードキャスターを作成
        broadcaster = EventBroadcaster(queue_maxsize=100)
        
        # セッション情報を保存
        session_info = SessionInfo(
            session_id=session_id,
            prompt=prompt,
            options=session_options,
            adapter=adapter,
            broadcaster=broadcaster
        )
        self.sessions[session_id] = session_info
        
        logger.info(f"Session created: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """セッション情報を取得する"""
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str) -> None:
        """セッションを削除する"""
        if session_id in self.sessions:
            session_info = self.sessions[session_id]
            if session_info.task and not session_info.task.done():
                session_info.task.cancel()
            del self.sessions[session_id]
            logger.info(f"Session removed: {session_id}")


# グローバルセッションマネージャーインスタンス
session_manager = SessionManager()


@app.post("/api/sessions", response_model=SessionCreateResponse, status_code=201)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    """セッションを作成する"""
    session_id = session_manager.create_session(
        prompt=request.prompt,
        options=request.options
    )
    
    return SessionCreateResponse(
        session_id=session_id,
        status="created"
    )


@app.websocket("/ws/sessions/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocketエンドポイント"""
    # セッションの存在確認
    session_info = session_manager.get_session(session_id)
    
    if not session_info:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await websocket.accept()
    
    try:
        # アダプターを実行してイベントをブロードキャスト
        async for event in session_info.adapter.run(
            session_info.prompt,
            session_info.options
        ):
            # ブロードキャスターを通じてイベントを送信
            enriched_event = session_info.broadcaster.enrich(session_id, event)
            await websocket.send_json(enriched_event)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error for session {session_id}: {e}")
    finally:
        # セッションリソースをクリーンアップ
        session_manager.remove_session(session_id)
