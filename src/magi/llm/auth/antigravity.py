"""Antigravity向けOAuth 2.0認証プロバイダ。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import socket
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
ANTIGRAVITY_VERSION = "1.15.8"
ANTIGRAVITY_ENDPOINT_DAILY = "https://daily.cloudcode-pa.googleapis.com"
ANTIGRAVITY_ENDPOINT_AUTOPUSH = "https://autopush.cloudcode-pa.googleapis.com"
ANTIGRAVITY_ENDPOINT_PROD = "https://cloudcode-pa.googleapis.com"
ANTIGRAVITY_ENDPOINTS = [
    ANTIGRAVITY_ENDPOINT_DAILY,
    ANTIGRAVITY_ENDPOINT_AUTOPUSH,
    ANTIGRAVITY_ENDPOINT_PROD,
]
ANTIGRAVITY_HEADERS = {
    "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Antigravity/{ANTIGRAVITY_VERSION} Chrome/138.0.7204.235 Electron/37.3.1 Safari/537.36",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
}
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


class DualStackServer(HTTPServer):
    """IPv6とIPv4の両方でリッスンを試みるサーバー
    
    環境に応じて柔軟にバインドを試みる。
    デフォルトではIPv6 (::) でリッスンし、IPv4も受け入れる設定を試みる。
    """
    
    address_family = socket.AF_INET6
    allow_reuse_address = True  # ポート再利用を許可

    def server_bind(self):
        # IPV6_V6ONLY を 0 に設定してデュアルスタック化を試みる
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()

class IPv4Server(HTTPServer):
    """IPv4専用の再利用可能サーバー"""
    address_family = socket.AF_INET
    allow_reuse_address = True


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
                self._send_response("Authentication failed. You can close this window.", is_error=True)
            elif "code" in query_params:
                code = query_params["code"][0]
                auth_state.code = code
                self._send_response("Authentication successful!", code=code)
            else:
                auth_state.error = "No code or error found in response"
                self._send_response("Invalid response. You can close this window.", is_error=True)
        finally:
            # 処理完了を通知
            auth_state.completed.set()
            
            # 自動検知メッセージを表示（標準入力待ちユーザーへのフィードバック）
            if auth_state.code:
                pass

    def _send_response(self, message: str, code: Optional[str] = None, is_error: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        # デザイン設定
        icon = "✓" if not is_error else "✕"
        icon_color = "#4CAF50" if not is_error else "#F44336"
        title = "認証に成功しました" if not is_error else "認証エラー"
        
        if is_error:
            description = f"<p style='color: #D32F2F;'>{message}</p>"
            fallback_html = ""
        else:
            description = "<p>このウィンドウを閉じて、ターミナルに戻ってください。</p>"
            fallback_html = f"""
            <div class="fallback">
                <p style="font-size: 14px; margin-bottom: 8px;">自動的に反応しない場合は、以下のコードをコピーしてターミナルに貼り付けてください：</p>
                <div class="code-container">
                    <span class="code" id="auth-code">{code}</span>
                    <button class="copy-btn" onclick="copyCode()">コピー</button>
                </div>
            </div>
            """

        html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #f4f7f6;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background: white;
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 400px;
            width: 90%;
        }}
        .icon {{
            color: {icon_color};
            font-size: 48px;
            margin-bottom: 1rem;
        }}
        h1 {{ font-size: 24px; color: #333; margin-bottom: 0.5rem; }}
        p {{ color: #666; line-height: 1.5; margin-bottom: 1.5rem; }}
        .code-container {{
            background: #f0f0f0;
            padding: 1rem;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
        }}
        .code {{ font-family: monospace; font-size: 16px; color: #333; word-break: break-all; }}
        .copy-btn {{
            background: #2196F3;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.2s;
            white-space: nowrap;
            margin-left: 10px;
        }}
        .copy-btn:hover {{ background: #1976D2; }}
        .footer {{ font-size: 12px; color: #999; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h1>{title}</h1>
        {description}
        {fallback_html}
        <div class="footer">MAGI System - Advanced Agentic Coding</div>
    </div>
    <script>
        function copyCode() {{
            const code = document.getElementById('auth-code').innerText;
            navigator.clipboard.writeText(code).then(() => {{
                const btn = document.querySelector('.copy-btn');
                btn.innerText = 'コピー完了';
                setTimeout(() => btn.innerText = 'コピー', 2000);
            }});
        }}
    </script>
</body>
</html>"""
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
        self._project_id: str | None = None

    def _get_headers(self, token: str) -> dict[str, str]:
        """Antigravity APIリクエスト用のヘッダーを生成する。"""
        headers = ANTIGRAVITY_HEADERS.copy()
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"
        return headers

    async def _fetch_with_fallback(
        self, url_suffix: str, headers: dict[str, str], json_body: dict[str, Any]
    ) -> httpx.Response:
        """複数のエンドポイントに対してフォールバックを行いながらリクエストを実行する。"""
        last_exception = None
        
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            for base_url in ANTIGRAVITY_ENDPOINTS:
                url = f"{base_url}{url_suffix}"
                try:
                    response = await client.post(url, headers=headers, json=json_body)
                    # 5xx エラーの場合は次のエンドポイントを試す
                    if 500 <= response.status_code < 600:
                        logger.warning(f"Endpoint {base_url} returned {response.status_code}. Retrying with next endpoint.")
                        continue
                    return response
                except (httpx.RequestError, asyncio.TimeoutError) as e:
                    logger.warning(f"Failed to connect to {base_url}: {e}. Retrying with next endpoint.")
                    last_exception = e
                    continue
        
        if last_exception:
            raise last_exception
        raise RuntimeError("All endpoints failed and no specific exception was caught.")

    def _extract_code_from_input(self, text: str) -> Optional[str]:
        import re
        text = text.strip()
        if not text:
            return None
            
        if "code=" in text:
            match = re.search(r'[?&]code=([^&]+)', text)
            if match:
                return match.group(1)

        code_match = re.search(r'(4/[0-9A-Za-z_-]+)', text)
        if code_match:
            return code_match.group(1)
            
        if not text.startswith("http") and len(text) > 10:
            return text
            
        return None

    def _readline(self) -> str:
        """標準入力から1行読み込む（テスト用に分離）"""
        return sys.stdin.readline()

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
        # ポートバインド戦略:
        # 1. まず IPv6 (Dual Stack) を試みる ("::")
        # 2. ダメなら IPv4 ("0.0.0.0") を試みる
        # 3. それでもダメなら従来の "127.0.0.1"
        
        server = None
        server_url_log = ""

        # 戦略1: Dual Stack (IPv6 + IPv4)
        try:
            # "::" はIPv6の全インターフェース。DualStackServerでIPv4も拾う設定にする。
            server = DualStackServer(("::", REDIRECT_PORT), OAuthCallbackHandler)
            server_url_log = f"http://localhost:{REDIRECT_PORT} (Dual Stack)"
        except (OSError, socket.error):
            # IPv6非対応などの場合、次へ
            pass

        # 戦略2: IPv4 Any (0.0.0.0)
        if server is None:
            try:
                server = IPv4Server(("0.0.0.0", REDIRECT_PORT), OAuthCallbackHandler)
                server_url_log = f"http://localhost:{REDIRECT_PORT} (IPv4 Any)"
            except OSError:
                pass

        # 戦略3: IPv4 Localhost (127.0.0.1) - 最終手段
        if server is None:
            try:
                server = IPv4Server(("127.0.0.1", REDIRECT_PORT), OAuthCallbackHandler)
                server_url_log = f"http://127.0.0.1:{REDIRECT_PORT}"
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    raise RuntimeError(
                        f"Port {REDIRECT_PORT} is already in use. Please stop other processes using this port."
                    )
                raise

        print(f"Local server running on {server_url_log}", file=sys.stderr)

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

            # プロンプト表示を少し遅らせる（ブラウザ起動メッセージとの被りを避けるため）
            # これにより「既存のブラウザセッション...」などの出力が先に出ることを期待
            time.sleep(2.0)

            # 4. コード待機（手動入力対応 & 自動検知並行）
            print("\nWaiting for authorization...")
            print("(If automatic redirect fails, paste the full redirect URL or code below)")
            print("Code: ", end="", flush=True)

            auth_code: Optional[str] = None
            start_time = time.time()
            
            # --- ハイブリッド待機ロジックの開始 ---

            # タスクA: ローカルサーバーからの通知待機
            async def wait_for_server() -> str:
                loop = asyncio.get_running_loop()
                while not auth_state.completed.is_set():
                    # threading.Eventを非同期に待つためにexecutorを使用
                    await loop.run_in_executor(None, auth_state.completed.wait, 0.5)
                    if auth_state.error:
                        raise RuntimeError(f"Authentication failed: {auth_state.error}")
                if auth_state.code:
                    return auth_state.code
                raise RuntimeError("No code received from server")

            # タスクB: 標準入力からの手動入力待機
            async def wait_for_input() -> str:
                loop = asyncio.get_running_loop()
                
                while True:
                    # プロンプトはすでに出ているので空文字
                    line = await loop.run_in_executor(None, self._readline)
                    if not line:
                        # EOF
                        raise RuntimeError("Stdin closed")
                    
                    text = line.strip()
                    extracted = self._extract_code_from_input(text)
                    if extracted:
                        return extracted
                    
                    # 無効な入力の場合
                    print(f"\nCould not detect code from input: '{text[:20]}...'")
                    print("Please paste the full URL or code again.")
                    print("Code: ", end="", flush=True)

            # タイムアウト付きで並行実行
            server_task = asyncio.create_task(wait_for_server())
            input_task = asyncio.create_task(wait_for_input())

            done, pending = await asyncio.wait(
                [server_task, input_task],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=self._timeout_seconds
            )

            # 結果処理
            if not done:
                # タイムアウト
                server_task.cancel()
                input_task.cancel()
                raise RuntimeError("Authentication timed out")

            # 完了したタスクから結果を取得
            for task in done:
                try:
                    auth_code = task.result()
                    break
                except Exception as e:
                    # エラーが発生した場合はもう一方のタスクの結果を見るか、エラーを伝播
                    logger.warning(f"Task failed: {e}")
                    pass
            
            # まだ auth_code が取れておらず、かつペンディングタスクがある場合
            if not auth_code and pending:
                # 残りのタスクを待機する（タイムアウトまで）
                elapsed = time.time() - start_time
                remaining = self._timeout_seconds - elapsed
                
                # wait(timeout=...) に負数を渡してエラーになるか、即時タイムアウトするのを防ぐ
                if remaining < 0.1:
                    remaining = 0.1

                done2, pending2 = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=remaining
                )
                for task in done2:
                    try:
                        auth_code = task.result()
                        break
                    except Exception as e:
                        logger.warning(f"Remaining task failed: {e}")
                pending = pending2

            # 残りのタスクをキャンセル
            for task in pending:
                task.cancel()

            if not auth_code:
                raise RuntimeError("Authentication failed or timed out")

            # 成功時の表示調整（入力待ちプロンプトの後始末）
            print()

        finally:
            server.shutdown()
            server.server_close()

        # 5. トークン交換
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
        if self._project_id:
            return self._project_id

        token = await self.get_token()
        url_suffix = "/v1internal:loadCodeAssist"
        headers = self._get_headers(token)
        body = {"metadata": {"ideType": "ANTIGRAVITY"}}

        try:
            response = await self._fetch_with_fallback(url_suffix, headers, body)
            if response.status_code == 401:
                token = await self.get_token(force_refresh=True)
                headers = self._get_headers(token)
                response = await self._fetch_with_fallback(url_suffix, headers, body)

            response.raise_for_status()
            data = response.json()

            project_info = data.get("cloudaicompanionProject")
            if isinstance(project_info, str):
                self._project_id = project_info
            elif isinstance(project_info, dict):
                self._project_id = project_info.get("id")

            if not self._project_id:
                logger.info("No project ID found in loadCodeAssist, attempting onboardUser...")
                self._project_id = await self._onboard_user()

            return self._project_id
        except Exception as e:
            logger.warning(f"Failed to get project ID from loadCodeAssist: {e}")
            # エラー時もオンボーディングを試みる
            self._project_id = await self._onboard_user()
            return self._project_id

    async def get_available_models(self) -> list[str]:
        """利用可能なモデルの一覧を取得する。"""
        token = await self.get_token()
        url_suffix = "/v1internal:fetchAvailableModels"
        headers = self._get_headers(token)
        body = {"metadata": {"ideType": "ANTIGRAVITY"}}

        try:
            response = await self._fetch_with_fallback(url_suffix, headers, body)
            if response.status_code == 401:
                token = await self.get_token(force_refresh=True)
                headers = self._get_headers(token)
                response = await self._fetch_with_fallback(url_suffix, headers, body)

            response.raise_for_status()
            data = response.json()

            models = data.get("models", [])
            if not isinstance(models, list):
                logger.warning(f"Unexpected response format for fetchAvailableModels: {data}")
                return []

            model_names = []
            for m in models:
                if isinstance(m, dict) and "name" in m:
                    model_names.append(m["name"])
                elif isinstance(m, str):
                    model_names.append(m)

            return sorted(model_names)
        except Exception as e:
            logger.warning(f"Failed to fetch available models: {e}")
            return []

    async def _onboard_user(self) -> str | None:
        """ユーザーのオンボーディング（プロジェクト作成）を試みる。"""
        token = await self.get_token()
        url_suffix = "/v1internal:onboardUser"
        headers = self._get_headers(token)
        body = {"metadata": {"ideType": "ANTIGRAVITY"}}

        max_attempts = 10
        delay_seconds = 5.0

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Onboarding attempt {attempt}/{max_attempts}...")
            try:
                response = await self._fetch_with_fallback(url_suffix, headers, body)
                if response.status_code == 401:
                    token = await self.get_token(force_refresh=True)
                    headers = self._get_headers(token)
                    response = await self._fetch_with_fallback(url_suffix, headers, body)

                response.raise_for_status()
                data = response.json()

                project_info = data.get("cloudaicompanionProject")
                project_id = None
                if isinstance(project_info, str):
                    project_id = project_info
                elif isinstance(project_info, dict):
                    project_id = project_info.get("id")

                if project_id:
                    logger.info(f"Onboarding successful. Project ID: {project_id}")
                    return project_id

                logger.warning(
                    f"Onboarding attempt {attempt} succeeded but no project ID returned."
                )
            except Exception as e:
                logger.warning(f"Onboarding attempt {attempt} failed: {e}")

            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)

        logger.error("All onboarding attempts failed.")
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
