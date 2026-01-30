"""
WebUIバックエンドアプリケーション

FastAPIを使用したWebUI用バックエンドサーバーの実装。
セッション管理、状態監視、リアルタイム通信のエンドポイントを提供する。
"""

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, APIRouter, status, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from magi.webui_backend.models import SessionOptions, SessionPhase
from magi.webui_backend.session_manager import SessionManager

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MAGI WebUI Backend",
    description="MAGIシステムのWebUI用バックエンドAPI",
    version="1.0.0",
)

# セッションマネージャーのインスタンス化
# 設定値は環境変数等から読み込むのが望ましいが、一旦デフォルト値で初期化
session_manager = SessionManager(max_concurrency=10, ttl_sec=600)

# APIルーターの定義
api_router = APIRouter(prefix="/api")


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンスモデル"""
    status: str


class CreateSessionRequest(BaseModel):
    """セッション作成リクエストモデル"""
    prompt: str
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
    return HealthResponse(status="ok")


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
            status="created"
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
    
    return CancelSessionResponse(status="cancelled")


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
        # 購読解除とセッションリソースのクリーンアップ
        await session_manager.broadcaster.unsubscribe(session_id, queue)
        # セッションの削除（必要に応じてキャンセルも実行）
        await session_manager.cancel_session(session_id)
        logger.info(f"WebSocket connection closed for session: {session_id}")
