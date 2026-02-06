"""
WebUIバックエンドアプリケーション

FastAPIを使用したWebUI用バックエンドサーバーの実装。
セッション管理、状態監視、リアルタイム通信のエンドポイントを提供する。
"""

import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, APIRouter, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError, Field

import os
from magi.config.manager import ConfigManager
from magi.errors import MagiException
from magi.webui_backend.models import SessionOptions, SessionPhase
from magi.webui_backend.session_manager import SessionManager
from magi.webui_backend.adapter import ConsensusEngineMagiAdapter, MockMagiAdapter

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    session_manager.start_cleanup_task()
    yield
    await session_manager.stop_cleanup_task()

app = FastAPI(
    title="MAGI WebUI Backend",
    description="MAGIシステムのWebUI用バックエンドAPI",
    version="1.0.0",
    lifespan=lifespan,
)

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "10"))
SESSION_TTL_SEC = int(os.environ.get("SESSION_TTL_SEC", "600"))
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "")

if CORS_ORIGINS:
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

# 設定読み込み
config_manager = ConfigManager()
try:
    config = config_manager.load()
    use_mock = False
except (MagiException, ValidationError, FileNotFoundError) as e:
    logger.warning(f"Configuration load failed, falling back to MockMagiAdapter: {e}")
    config = None
    use_mock = True

# 環境変数でMock強制も可能にする (例: MAGI_USE_MOCK=1)
if os.environ.get("MAGI_USE_MOCK", "0") == "1":
    use_mock = True

def create_adapter():
    if use_mock or config is None:
        return MockMagiAdapter()
    return ConsensusEngineMagiAdapter(config=config)

# セッションマネージャーのインスタンス化
session_manager = SessionManager(
    max_concurrency=MAX_CONCURRENCY, 
    ttl_sec=SESSION_TTL_SEC,
    adapter_factory=create_adapter
)

# APIルーターの定義
api_router = APIRouter(prefix="/api")


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンスモデル"""
    status: str
    mode: str = "production"  # "mock" or "production"


class CreateSessionRequest(BaseModel):
    """セッション作成リクエストモデル"""
    prompt: str = Field(..., min_length=1, max_length=8000)
    options: Optional[SessionOptions] = None


class CreateSessionResponse(BaseModel):
    """セッション作成レスポンスモデル"""
    session_id: str
    ws_url: str
    status: str


class CancelSessionResponse(BaseModel):
    """セッションキャンセルレスポンスモデル"""
    status: str


@api_router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """ヘルスチェックエンドポイント

    Returns:
        HealthResponse: サーバーの状態
    """
    return HealthResponse(
        status="ok",
        mode="mock" if use_mock else "production"
    )


@api_router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "同時実行数制限超過"}
    }
)
async def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    """新規セッション作成エンドポイント

    Args:
        request: セッション作成リクエスト

    Returns:
        CreateSessionResponse: 作成されたセッション情報

    Raises:
        HTTPException(429): 同時実行数が上限に達している場合
    """
    try:
        session_id = await session_manager.create_session(
            prompt=request.prompt,
            options=request.options
        )
        # 初期状態は QUEUED だが、create_session 直後は RUNNING (非同期タスク起動) とみなすことも可能
        # ここでは単純に QUEUED/RUNNING を返す
        return CreateSessionResponse(
            session_id=session_id,
            ws_url=f"/ws/sessions/{session_id}",
            status="QUEUED"
        )
    except RuntimeError as e:
        # 同時実行数制限など
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )


@api_router.post("/sessions/{session_id}/cancel", response_model=CancelSessionResponse)
async def cancel_session(session_id: str) -> CancelSessionResponse:
    """セッションキャンセルエンドポイント

    Args:
        session_id: キャンセル対象のセッションID

    Returns:
        CancelSessionResponse: キャンセル結果
    """
    success = await session_manager.cancel_session(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    return CancelSessionResponse(status="CANCELLED")


# ルーターをアプリケーションに登録
app.include_router(api_router)


@app.websocket("/ws/sessions/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocketセッション接続エンドポイント

    Args:
        websocket: WebSocket接続
        session_id: 接続先セッションID
    """
    await websocket.accept()

    # セッション存在確認
    session = session_manager.get_session(session_id)
    if not session:
        # 400系エラーでクローズ (Policy Violation などを利用)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # イベント購読
    queue = await session_manager.broadcaster.subscribe(session_id)

    # 送信タスク
    async def sender():
        try:
            while True:
                data = await queue.get()
                
                # イベントのエンリッチメント（session_idの付与など）
                if "session_id" not in data:
                    data["session_id"] = session_id
                
                await websocket.send_json(data)
                
                # 終了判定: finalイベント または 特定のフェーズへの遷移
                # EventBroadcasterにより type, phase, session_id 等が含まれている想定
                evt_type = data.get("type")
                phase = data.get("phase")
                
                if evt_type == "final":
                    await websocket.close()
                    break
                
                if evt_type == "error":
                    await websocket.close()
                    break

                if evt_type == "phase" and phase in [
                    SessionPhase.RESOLVED.value,
                    SessionPhase.CANCELLED.value,
                    SessionPhase.ERROR.value
                ]:
                    await websocket.close()
                    break
                    
        except Exception as e:
            # 送信エラー時などはループを抜けて終了処理へ
            logger.exception(f"Sender task error for session {session_id}: {e}")

    # 受信タスク（切断検知用）
    async def receiver():
        try:
            while True:
                # クライアントからのデータは受信するが無視する
                await websocket.receive_text()
        except Exception as e:
            # 切断時
            logger.debug(f"Receiver task ended for session {session_id}: {e}")

    sender_task = asyncio.create_task(sender())
    receiver_task = asyncio.create_task(receiver())

    try:
        # どちらかのタスクが終了するまで待機（送信完了 or 切断）
        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
    finally:
        # 購読解除
        await session_manager.broadcaster.unsubscribe(session_id, queue)
        
        # セッションのクリーンアップ判定
        # 以下の条件を満たす場合のみcancel_sessionを呼び出す:
        # 1. セッションがまだアクティブ(未完了)である
        # 2. 他にアクティブなサブスクライバーが残っていない
        try:
            is_active = session_manager.is_session_active(session_id)
            subscriber_count = await session_manager.broadcaster.get_subscriber_count(session_id)
            
            if is_active and subscriber_count == 0:
                # セッションが未完了で、かつ他のサブスクライバーがいない場合のみキャンセル
                await session_manager.cancel_session(session_id)
                logger.info(f"Session cancelled due to no remaining subscribers: {session_id}")
            else:
                logger.info(
                    f"WebSocket connection closed for session: {session_id} "
                    f"(active={is_active}, subscribers={subscriber_count})"
                )
        except Exception as e:
            # クリーンアップ処理でのエラーはログに記録するが、例外は伝播させない
            logger.exception(f"Error during session cleanup for {session_id}: {e}")

