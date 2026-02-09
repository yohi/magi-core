"""Antigravity向けOAuth 2.0認証プロバイダ。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import sys
import threading
import time
import warnings
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from magi.llm.auth.base import AuthContext, AuthProvider
from magi.llm.auth.storage import TokenManager

logger = logging.getLogger(__name__)

# Antigravity (Google OAuth) Constants
DEFAULT_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]
REDIRECT_PORT = 51121
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/oauth-callback"


class AuthState:
    """認証結果を保持するクラス"""

    def __init__(self) -> None:
        self.code: Optional[str] = None
        self.error: Optional[str] = None
        self.completed = threading.Event()


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """OAuthコールバックを処理するハンドラ"""

    def do_GET(self) -> None:
        """GETリクエストを処理する"""
        parsed_url = urlparse(self.path)
        if parsed_url.path != "/oauth-callback":
            self.send_error(404, "Not Found")
            return

        # サーバーインスタンスから状態オブジェクトを取得
        auth_state: Optional[AuthState] = getattr(self.server, "auth_state", None)
        if not auth_state:
            self.send_error(500, "Server configuration error")
            return

        try:
            query_params = parse_qs(parsed_url.query)

            if "error" in query_params:
                auth_state.error = query_params["error"][0]
                self._send_response("Authentication failed. You can close this window.")
            elif "code" in query_params:
                code = query_params["code"][0]
                auth_state.code = code
                self._send_response("Authentication successful!", code=code)
            else:
                auth_state.error = "No code or error found in response"
                self._send_response("Invalid response. You can close this window.")
        finally:
            # 処理完了を通知
            auth_state.completed.set()

    def _send_response(self, message: str, code: Optional[str] = None) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        code_html = ""
        if code:
            code_html = f"""
            <div style="margin-top: 20px; padding: 15px; background-color: #f5f5f5; border-radius: 5px; border: 1px solid #ddd;">
                <p style="margin: 0 0 10px; color: #666; font-size: 14px;">
                    もしCLIが自動的に反応しない場合は、以下のコードをコピーしてターミナルに貼り付けてください:
                </p>
                <div style="font-family: monospace; font-size: 16px; font-weight: bold; word-break: break-all; color: #333; padding: 10px; background: #fff; border: 1px solid #ccc; border-radius: 3px; max-height: 200px; overflow-y: auto;">
                    {code}
                </div>
                <button onclick="copyCode()" style="margin-top: 10px; padding: 5px 10px; cursor: pointer;">コードをコピー</button>
            </div>
            <script>
            function copyCode() {{
                const code = `{code}`;
                navigator.clipboard.writeText(code).then(() => {{
                    alert("クリップボードにコピーしました");
                }}).catch(err => {{
                    console.error("Failed to copy: ", err);
                }});
            }}
            </script>
            """

        html = f"""
        <html>
        <head>
            <title>Authentication Status</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: sans-serif; text-align: center; padding-top: 50px; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #4CAF50;">{message}</h2>
            <p>You can close this window.</p>
            {code_html}
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """ログ出力を抑制"""
        pass


class AntigravityAuthProvider(AuthProvider):
    """Antigravity向けのOAuth 2.0認証（PKCE）とリフレッシュを管理する。"""

    def __init__(
        self,
        context: AuthContext,
        token_manager: TokenManager | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        """AntigravityAuthProviderを初期化する。

        Args:
            context: 認証に必要な設定情報。
            token_manager: トークン保存先。
            timeout_seconds: 認証フローの待機タイムアウト。
        """

        self._context = context
        # デフォルト値の補完
        if not self._context.auth_url:
            self._context.auth_url = DEFAULT_AUTH_URL
        if not self._context.token_url:
            self._context.token_url = DEFAULT_TOKEN_URL
        if not self._context.scopes:
            self._context.scopes = DEFAULT_SCOPES

        self._token_manager = token_manager or TokenManager()
        self._timeout_seconds = timeout_seconds
        self._service_name = "magi.antigravity"
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[str] | None = None

    async def authenticate(self) -> None:
        """初回認証を行い、トークンを保存する（PKCEフロー）。"""

        # 1. PKCE Verifier & Challenge 生成
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()
            )
            .decode("ascii")
            .rstrip("=")
        )

        # 2. ローカルサーバー起動
        # 固定ポートを使用（Google Cloud Consoleで登録済みのURIと一致させるため）
        host = "127.0.0.1"
        try:
            server = HTTPServer((host, REDIRECT_PORT), OAuthCallbackHandler)
            print(f"Local server running on http://{host}:{REDIRECT_PORT}", file=sys.stderr)
        except OSError as e:
            if e.errno == 98:  # Address already in use
                raise RuntimeError(
                    f"Port {REDIRECT_PORT} is already in use. Please stop other processes using this port."
                )
            raise

        # 状態オブジェクトをサーバーにアタッチ
        auth_state = AuthState()
        server.auth_state = auth_state  # type: ignore

        # リダイレクトURIを固定値に設定
        redirect_uri = REDIRECT_URI

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        try:
            # 3. 認証URL生成 & ブラウザ起動
            params = {
                "response_type": "code",
                "client_id": self._require_client_id(),
                "redirect_uri": redirect_uri,
                "scope": " ".join(self._context.scopes),
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",  # Refresh Token取得に必須
                "prompt": "consent",  # 常に同意画面を表示（Refresh Token確実取得のため）
            }
            auth_url = f"{self._context.auth_url}?{urlencode(params)}"

            print(f"Opening browser for authentication: {auth_url}")
            webbrowser.open(auth_url)

            # 4. コード待機（手動入力対応）
            print("\n" + "=" * 60)
            print("【手動認証の手順 (Manual Authentication Steps)】")
            print("1. ブラウザでGoogleアカウントにログインし、アクセスを許可してください。")
            print("2. 認証後、ブラウザが 'http://localhost:51121/...' にリダイレクトされます。")
            print("3. もし「接続が拒否されました (Connection refused)」等のエラーが表示されても")
            print("   **認証は成功しています**。")
            print("4. エラー画面の **アドレスバーのURLすべて** をコピーしてください。")
            print("   または、認証成功画面に表示された **認証コード** をコピーしてください。")
            print("5. コピーしたURLまたはコードを以下に貼り付けて、Enterキーを押してください。")
            print("   (自動的に検知された場合は、何も入力せずにEnterを押してください)")
            print("=" * 60 + "\n")

            auth_code = None
            start_time = time.time()

            while not auth_code:
                # タイムアウトチェック
                if time.time() - start_time > self._timeout_seconds:
                    raise RuntimeError("Authentication timed out")
                
                if auth_state.error:
                    raise RuntimeError(f"Authentication failed: {auth_state.error}")

                # ユーザー入力を待機（非ブロッキングにするため run_in_executor を使用）
                # これによりバックグラウンドのサーバー処理を阻害しない
                try:
                    # プロンプトを表示して入力を待つ
                    # 注意: input() はブロックするため、サーバーからの自動検知をリアルタイムに反映するには
                    # ユーザーがEnterを押す必要がある。
                    redirect_url_or_empty = await asyncio.to_thread(input, "Paste URL or Code here (or Enter to check auto-detect): ")
                    redirect_url_or_empty = redirect_url_or_empty.strip()
                except (EOFError, KeyboardInterrupt):
                    raise RuntimeError("Authentication canceled by user")

                    # 1. ユーザー入力からコード抽出を試みる
                if redirect_url_or_empty:
                    import re
                    # 指定された正規表現パターンでコードをピンポイントで探す
                    code_match = re.search(r'(4/[0-9A-Za-z_-]+)', redirect_url_or_empty)
                    if code_match:
                        auth_code = code_match.group(1)
                    else:
                        # URLパラメータ解析 (フォールバック)
                        # code=... のパターンを探す
                        match = re.search(r'[?&]code=([^&]+)', redirect_url_or_empty)
                        if match:
                            auth_code = match.group(1)
                        # code= がない場合、入力値そのものがコードである可能性
                        elif not redirect_url_or_empty.startswith("http") and len(redirect_url_or_empty) > 10:
                            # URL形式でなく、ある程度の長さがあればコードとみなす
                            auth_code = redirect_url_or_empty
                    
                    if auth_code:
                        print("Manual code entry detected.")
                        print("サーバーを停止しています... (Stopping local server...)")
                        break
                    else:
                        print("入力からコードを検出できませんでした。もう一度試してください。")

                # 2. 自動検知（ローカルサーバー）の結果を確認
                if auth_state.code:
                    auth_code = auth_state.code
                    print("\nAuto-authentication detected.")
                    break
                
                if auth_state.error:
                    raise RuntimeError(f"Authentication failed: {auth_state.error}")

            if not auth_code:
                raise RuntimeError("Failed to receive authorization code")

        finally:
            print("サーバーを停止しています... (Stopping local server...)")
            server.shutdown()
            server.server_close()

        # 5. トークン交換
        print("認証コードをトークンと交換しています... (Exchanging code for tokens...)")
        token_payload = await self._exchange_code_for_token(
            auth_code, code_verifier, redirect_uri
        )
        self._store_tokens(token_payload)

    async def _exchange_code_for_token(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> dict[str, Any]:
        """認可コードをトークンと交換する"""
        token_url = self._require_token_url()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._require_client_id(),
            "code_verifier": code_verifier,
        }
        if self._context.client_secret:
            data["client_secret"] = self._context.client_secret

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                token_url, data=data, headers={"Accept": "application/json"}
            )

        if response.is_error:
            logger.error(f"Token exchange failed: {response.text}")
            response.raise_for_status()

        return response.json()

    async def get_token(self, force_refresh: bool = False) -> str:
        """有効なアクセストークンを返す。必要ならリフレッシュする。

        Args:
            force_refresh: 強制的にリフレッシュするかどうか。
        """

        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            await self.authenticate()
            stored = self._token_manager.get_token(self._service_name)

        if not stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")

        if not force_refresh:
            token = self._extract_access_token(stored)
            if token is not None:
                return token

        return await self._refresh_queue(stored)

    async def _refresh_queue(self, stored: str) -> str:
        if self._refresh_task is not None:
            return await self._refresh_task

        async with self._refresh_lock:
            if self._refresh_task is not None:
                return await self._refresh_task

            self._refresh_task = asyncio.create_task(self._refresh_token(stored))

        try:
            if self._refresh_task is None:
                raise RuntimeError("Failed to create refresh task")
            return await self._refresh_task
        finally:
            self._refresh_task = None

    async def _refresh_token(self, stored: str) -> str:
        refresh_token = self._extract_refresh_token(stored)
        if refresh_token:
            token_payload = await self._refresh_token_flow(refresh_token)
            self._store_tokens(token_payload, refresh_token_fallback=refresh_token)
        else:
            warnings.warn(
                "refresh_tokenが無いため再認証します。",
                RuntimeWarning,
                stacklevel=2,
            )
            await self.authenticate()
            new_stored = self._token_manager.get_token(self._service_name)
            if not new_stored:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            token = self._extract_access_token(new_stored)
            if token is None:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            return token

        latest_stored = self._token_manager.get_token(self._service_name)
        if not latest_stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        token = self._extract_access_token(latest_stored)
        if token is None:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        return token

    # 不要な古いメソッドを削除

    async def get_project_id(self) -> str | None:
        """トークンを使用してProject IDを取得する（未実装）"""
        # TODO: /v1internal:loadCodeAssist エンドポイントを叩いてProject IDを取得する実装を追加
        return None

    async def _refresh_token_flow(self, refresh_token: str) -> dict[str, Any]:
        token_url = self._require_token_url()

        # Antigravity特有: refresh_token|projectId|managedProjectId 形式への対応
        # 実際のOAuthリクエストには生のrefresh_tokenのみを送る
        raw_refresh_token = refresh_token.split("|")[0]

        data = {
            "grant_type": "refresh_token",
            "refresh_token": raw_refresh_token,
            "client_id": self._require_client_id(),
        }
        if self._context.client_secret:
            data["client_secret"] = self._context.client_secret

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                token_url, data=data, headers={"Accept": "application/json"}
            )

        if response.is_error:
            logger.error(f"Token refresh failed: {response.text}")
            response.raise_for_status()

        return response.json()

    def _store_tokens(
        self, token_payload: dict[str, Any], refresh_token_fallback: str | None = None
    ) -> None:
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str):
            raise RuntimeError("アクセストークンが取得できませんでした。")

        # レスポンスにrefresh_tokenが含まれていればそれを使い、なければフォールバック（既存のもの）を使用
        refresh_token = token_payload.get("refresh_token") or refresh_token_fallback

        expires_at = None
        expires_in = token_payload.get("expires_in")
        if isinstance(expires_in, (int, float)):
            # 安全マージンとして60秒引く（Antigravity仕様に合わせる）
            expires_at = int(time.time() + float(expires_in) - 60)

        stored_payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": token_payload.get("token_type"),
            # 必要に応じてProject IDなどをここに追加できる
        }
        self._token_manager.set_token(
            self._service_name, json.dumps(stored_payload, ensure_ascii=False)
        )

    def _extract_access_token(self, stored: str) -> str | None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        expires_at = payload.get("expires_at")
        # 期限切れ判定
        if isinstance(expires_at, (int, float)) and time.time() >= float(expires_at):
            return None

        token = payload.get("access_token")
        if isinstance(token, str):
            return token
        return None

    def _extract_refresh_token(self, stored: str) -> str | None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        token = payload.get("refresh_token")
        if isinstance(token, str):
            return token
        return None

    def _require_client_id(self) -> str:
        if not self._context.client_id:
            raise RuntimeError("client_idが未設定です。")
        return self._context.client_id

    def _require_token_url(self) -> str:
        if not self._context.token_url:
            # デフォルト値を返す
            return DEFAULT_TOKEN_URL
        return self._context.token_url
