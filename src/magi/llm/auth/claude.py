"""Claude OAuth 2.1 (PKCE) 認証プロバイダ。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse
import warnings
import webbrowser

import httpx

from magi.llm.auth.base import AuthContext, AuthProvider
from magi.llm.auth.storage import TokenManager

DEFAULT_AUTH_URL = "https://auth.anthropic.com/authorize"
DEFAULT_TOKEN_URL = "https://auth.anthropic.com/token"


class _AuthCallbackServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, _AuthCallbackHandler)
        self.auth_code: str | None = None
        self.auth_error: str | None = None
        self.event = threading.Event()


class _AuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        query = parse_qs(parsed.query)
        code = query.get("code", [None])[0]
        error = query.get("error", [None])[0]
        server = self.server
        if isinstance(server, _AuthCallbackServer):
            server.auth_code = code
            server.auth_error = error
            server.event.set()

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Authentication successful. You can close this window.")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class ClaudeAuthProvider(AuthProvider):
    """Claude向けOAuth 2.1 (PKCE) 認証を実行する。"""

    def __init__(
        self,
        context: AuthContext,
        token_manager: TokenManager | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        """ClaudeAuthProviderを初期化する。

        Args:
            context: 認証に必要な設定情報。
            token_manager: トークン保存先。
            timeout_seconds: コールバック待機タイムアウト。
        """

        self._context = context
        self._token_manager = token_manager or TokenManager()
        self._timeout_seconds = timeout_seconds
        self._service_name = "magi.claude"

    async def authenticate(self) -> None:
        """ブラウザ認証フローを実行し、トークンを保存する。"""

        verifier = self._generate_verifier()
        challenge = self._generate_challenge(verifier)

        if self._context.redirect_uri:
            parsed = urlparse(self._context.redirect_uri)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port if parsed.port is not None else 0
            server = _AuthCallbackServer((host, port))
        else:
            server = _AuthCallbackServer(("127.0.0.1", 0))

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            port = server.server_address[1]
            if self._context.redirect_uri:
                parsed = urlparse(self._context.redirect_uri)
                scheme = parsed.scheme or "http"
                host = parsed.hostname or "localhost"
                path = parsed.path or "/callback"
                redirect_uri = f"{scheme}://{host}:{port}{path}"
            else:
                redirect_uri = f"http://localhost:{port}/callback"

            auth_url = self._build_auth_url(redirect_uri, challenge)
            await asyncio.to_thread(webbrowser.open, auth_url)

            received = await asyncio.to_thread(server.event.wait, self._timeout_seconds)
            if not received:
                raise TimeoutError("認証のコールバックがタイムアウトしました。")
            if server.auth_error:
                raise RuntimeError(f"認証エラーが返されました: {server.auth_error}")
            if not server.auth_code:
                raise RuntimeError("認証コードが取得できませんでした。")

            tokens = await self._exchange_code_for_token(
                code=server.auth_code,
                verifier=verifier,
                redirect_uri=redirect_uri,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self._store_tokens(tokens)

    async def get_token(self, force_refresh: bool = False) -> str:
        """有効なアクセストークンを返す。

        Args:
            force_refresh: キャッシュを無視して強制的にトークンを更新するかどうか。

        Returns:
            str: アクセストークン。
        """

        if force_refresh:
            await self.authenticate()

        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            await self.authenticate()
            stored = self._token_manager.get_token(self._service_name)

        if not stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")

        token_value = self._extract_access_token(stored)
        if token_value is None:
            await self.authenticate()
            stored = self._token_manager.get_token(self._service_name)
            if not stored:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            token_value = self._extract_access_token(stored)

        if token_value is None:
            raise RuntimeError("アクセストークンが取得できませんでした。")

        return token_value

    def _build_auth_url(self, redirect_uri: str, challenge: str) -> str:
        base_url = self._context.auth_url or DEFAULT_AUTH_URL
        client_id = self._require_client_id()
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self._context.scopes:
            params["scope"] = " ".join(self._context.scopes)
        if self._context.audience:
            params["audience"] = self._context.audience

        query = httpx.QueryParams(params)
        return f"{base_url}?{query}"

    async def _exchange_code_for_token(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        token_url = self._context.token_url or DEFAULT_TOKEN_URL
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._require_client_id(),
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        }
        if self._context.client_secret:
            data["client_secret"] = self._context.client_secret

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(token_url, data=data, headers={"Accept": "application/json"})
        response.raise_for_status()
        token_payload = response.json()
        if "access_token" not in token_payload:
            raise RuntimeError("アクセストークンがレスポンスに含まれていません。")
        return token_payload

    def _store_tokens(self, token_payload: dict[str, Any]) -> None:
        access_token = token_payload.get("access_token")
        if not access_token:
            raise RuntimeError("アクセストークンが取得できませんでした。")

        expires_at = None
        expires_in = token_payload.get("expires_in")
        if isinstance(expires_in, (int, float)):
            expires_at = int(time.time() + float(expires_in))

        stored_payload = {
            "access_token": access_token,
            "refresh_token": token_payload.get("refresh_token"),
            "expires_at": expires_at,
            "token_type": token_payload.get("token_type"),
        }
        self._token_manager.set_token(self._service_name, json.dumps(stored_payload, ensure_ascii=False))

    def _extract_access_token(self, stored: str) -> str | None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return stored

        if not isinstance(payload, dict):
            return stored

        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)) and time.time() >= float(expires_at):
            warnings.warn(
                "アクセストークンが期限切れのため再認証します。",
                RuntimeWarning,
                stacklevel=2,
            )
            return None

        token = payload.get("access_token")
        if isinstance(token, str):
            return token
        return None

    def _require_client_id(self) -> str:
        if not self._context.client_id:
            raise RuntimeError("client_idが未設定です。")
        return self._context.client_id

    def _generate_verifier(self) -> str:
        return self._base64_url_encode(secrets.token_bytes(32))

    def _generate_challenge(self, verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        return self._base64_url_encode(digest)

    def _base64_url_encode(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
