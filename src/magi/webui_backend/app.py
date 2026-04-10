"""
WebUIバックエンドアプリケーション

FastAPIを使用したWebUI用バックエンドサーバーの実装。
セッション管理、状態監視、リアルタイム通信のエンドポイントを提供する。
"""

import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, APIRouter, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError, Field

import os
from magi.config.manager import ConfigManager
from magi.errors import MagiException
from magi.webui_backend.models import SessionOptions, SessionPhase
from magi.webui_backend.session_manager import SessionManager
from magi.webui_backend.adapter import ConsensusEngineMagiAdapter, MockMagiAdapter
from magi.webui_backend.models_fetcher import ModelsFetcher

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

# モックモードの判定
def is_mock_enabled() -> bool:
    val = os.environ.get("MAGI_USE_MOCK", "0").lower()
    return val in ("1", "true", "yes", "on")

config_manager = ConfigManager()
use_mock = False
models_fetcher = None

try:
    config = config_manager.load()
    use_mock = is_mock_enabled()
    models_fetcher = ModelsFetcher(config)
    if use_mock:
        logger.info("MAGI_USE_MOCK is enabled via environment variable. Forcing MOCK_MODE.")
    else:
        logger.info("Configuration loaded successfully. Running in PRODUCTION_MODE.")
except (MagiException, ValidationError, FileNotFoundError) as e:
    if is_mock_enabled():
        logger.warning(f"Configuration load failed, falling back to MockMagiAdapter as requested: {e}")
        from magi.config.settings import MagiSettings
        config = MagiSettings()  # デフォルト値を使用
        use_mock = True
        models_fetcher = ModelsFetcher(config)
    else:
        logger.error(f"Failed to load configuration and MAGI_USE_MOCK is not enabled: {e}")
        # ユーザーが明示的に 0 を指定しているか、デフォルト状態（未指定）の場合はエラーにする
        raise e

MAX_CONCURRENCY = config.max_concurrency
SESSION_TTL_SEC = config.session_ttl_sec
# CORSの設定
CORS_ORIGINS = config.cors_origins
# デフォルトでローカル開発環境を許可
origins = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]

if CORS_ORIGINS:
    if CORS_ORIGINS.strip() == "*":
        origins = ["*"]
    else:
        user_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
        if user_origins:
            origins.extend(user_origins)

# 重複排除
if "*" not in origins:
    origins = list(set(origins))

# CORSMiddleware の設定
# "*" が含まれる場合は allow_credentials を True に設定できない (ブラウザの制限)
allow_all = "*" in origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

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


@api_router.get("/models")
async def get_models():
    """利用可能なモデルの一覧を取得するエンドポイント"""
    if models_fetcher:
        models = await models_fetcher.fetch_models()
        return {"models": models}
    return {"models": []}


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

# フロントエンドの静的ファイル配信
dist_path = Path("frontend/dist")
if dist_path.exists():
    # assetsディレクトリのマウント
    assets_path = dist_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API へのリクエストは本来 api_router で処理されるが、
        # 存在しないエンドポイントの場合に SPA の index.html にフォールバックしないようにする
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        # それ以外のリクエストは index.html を返す (SPA)
        file_path = dist_path / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_path / "index.html")
else:
    logger.warning(f"frontend/dist directory not found at {dist_path.absolute()}. Frontend will not be served.")


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
                    # 最終結果を送信した後、少し待ってからクローズ（クライアント側の処理時間を確保）
                    await asyncio.sleep(0.5)
                    await websocket.close()
                    break
                
                if evt_type == "error":
                    await websocket.close()
                    break

                # フェーズ遷移による終了判定は、RESOLVED以外（CANCELLED, ERROR）のみに限定する
                # RESOLVED の場合は final イベントがセットで来るはずなのでそちらで閉じる
                if evt_type == "phase" and phase in [
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


if __name__ == "__main__":
    import uvicorn
    import os
    
    host = os.getenv("HOST", "127.0.0.1")
    port_str = os.getenv("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"Invalid PORT environment variable: '{port_str}'. Falling back to 8000.")
        port = 8000
        
    uvicorn.run(app, host=host, port=port)

