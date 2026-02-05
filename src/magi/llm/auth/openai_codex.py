"""OpenAI Codex CLI向けOAuth 2.1 (PKCE) 認証プロバイダ。"""

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
import jwt

from magi.llm.auth.base import AuthContext, AuthProvider
from magi.llm.auth.storage import TokenManager

DEFAULT_AUTH_URL = "https://auth.openai.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_SCOPES = ["openid", "profile", "email", "offline_access"]
DEFAULT_REDIRECT_PORT = 1455
DEFAULT_REDIRECT_PATH = "/auth/callback"


class _AuthCallbackServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], expected_path: str) -> None:
        super().__init__(server_address, _AuthCallbackHandler)
        self.auth_code: str | None = None
        self.auth_error: str | None = None
        self.event = threading.Event()
        self.expected_path = expected_path


class _AuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        server = self.server
        expected_path = DEFAULT_REDIRECT_PATH
        if isinstance(server, _AuthCallbackServer):
            expected_path = server.expected_path
        if parsed.path != expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        query = parse_qs(parsed.query)
        code = query.get("code", [None])[0]
        error = query.get("error", [None])[0]
        if isinstance(server, _AuthCallbackServer):
            server.auth_code = code
            server.auth_error = error
            server.event.set()

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Authentication successful. You can close this window.")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class OpenAICodexAuthProvider(AuthProvider):
    """OpenAI Codex CLI向けのOAuth 2.1 (PKCE) 認証を実行する。"""

    def __init__(
        self,
        context: AuthContext,
        token_manager: TokenManager | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        """OpenAICodexAuthProviderを初期化する。

        Args:
            context: 認証に必要な設定情報。
            token_manager: トークン保存先。
            timeout_seconds: コールバック待機タイムアウト。
        """

        self._context = context
        self._token_manager = token_manager or TokenManager()
        self._timeout_seconds = timeout_seconds
        self._service_name = "magi.openai_codex"
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[str] | None = None
        self._chatgpt_account_id: str | None = None

    async def authenticate(self) -> None:
        """ブラウザ認証フローを実行し、トークンを保存する。"""

        verifier = self._generate_verifier()
        challenge = self._generate_challenge(verifier)

        server, redirect_uri = self._create_callback_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
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

        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            await self.authenticate()
            stored = self._token_manager.get_token(self._service_name)

        if not stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")

        if force_refresh:
            return await self._refresh_queue(stored)

        token = self._extract_access_token(stored)
        if token is not None:
            self._ensure_chatgpt_account_id(stored)
            return token

        return await self._refresh_queue(stored)

    def _create_callback_server(self) -> tuple[_AuthCallbackServer, str]:
        redirect_uri = self._context.redirect_uri
        if redirect_uri:
            parsed = urlparse(redirect_uri)
            if not parsed.hostname or not parsed.port or not parsed.path:
                raise RuntimeError("redirect_uriが不正です。")
            server = _AuthCallbackServer((parsed.hostname, parsed.port), parsed.path)
            return server, redirect_uri

        try:
            server = _AuthCallbackServer(("127.0.0.1", DEFAULT_REDIRECT_PORT), DEFAULT_REDIRECT_PATH)
        except OSError:
            server = _AuthCallbackServer(("127.0.0.1", 0), DEFAULT_REDIRECT_PATH)

        port = server.server_address[1]
        redirect_uri = f"http://localhost:{port}{DEFAULT_REDIRECT_PATH}"
        return server, redirect_uri

    def _build_auth_url(self, redirect_uri: str, challenge: str) -> str:
        base_url = self._context.auth_url or DEFAULT_AUTH_URL
        client_id = self._context.client_id or DEFAULT_CLIENT_ID
        scopes = self._context.scopes or DEFAULT_SCOPES
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(scopes),
            "codex_cli_simplified_flow": "true",
            "originator": "codex_cli_rs",
            "id_token_add_organizations": "true",
        }
        query = httpx.QueryParams(params)
        return f"{base_url}?{query}"

    async def _exchange_code_for_token(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        token_url = self._context.token_url or DEFAULT_TOKEN_URL
        client_id = self._context.client_id or DEFAULT_CLIENT_ID
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(token_url, data=data, headers={"Accept": "application/json"})
        response.raise_for_status()
        token_payload = response.json()
        if "access_token" not in token_payload:
            raise RuntimeError("アクセストークンがレスポンスに含まれていません。")
        return token_payload

    async def _refresh_queue(self, stored: str) -> str:
        if self._refresh_task:
            return await self._refresh_task

        async with self._refresh_lock:
            if self._refresh_task:
                return await self._refresh_task

            self._refresh_task = asyncio.create_task(self._refresh_token(stored))

        try:
            return await self._refresh_task
        finally:
            self._refresh_task = None

    async def _refresh_token(self, stored: str) -> str:
        refresh_token = self._extract_refresh_token(stored)
        if not refresh_token:
            warnings.warn(
                "refresh_tokenが無いため再認証します。",
                RuntimeWarning,
                stacklevel=2,
            )
            await self.authenticate()
            stored = self._token_manager.get_token(self._service_name)
            if not stored:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            token = self._extract_access_token(stored)
            if token is None:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            self._ensure_chatgpt_account_id(stored)
            return token

        token_payload = await self._refresh_token_flow(refresh_token)
        self._store_tokens(token_payload, refresh_token_fallback=refresh_token)

        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        token = self._extract_access_token(stored)
        if token is None:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        self._ensure_chatgpt_account_id(stored)
        return token

    async def _refresh_token_flow(self, refresh_token: str) -> dict[str, Any]:
        token_url = self._context.token_url or DEFAULT_TOKEN_URL
        client_id = self._context.client_id or DEFAULT_CLIENT_ID
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(token_url, data=data, headers={"Accept": "application/json"})
        response.raise_for_status()
        token_payload = response.json()
        if "access_token" not in token_payload:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        return token_payload

    def _store_tokens(self, token_payload: dict[str, Any], refresh_token_fallback: str | None = None) -> None:
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str):
            raise RuntimeError("アクセストークンが取得できませんでした。")

        refresh_token = token_payload.get("refresh_token") or refresh_token_fallback
        id_token = token_payload.get("id_token")
        id_token_claims = self._decode_id_token(id_token) if isinstance(id_token, str) else {}
        self._update_chatgpt_account_id(id_token_claims)

        expires_at = None
        expires_in = token_payload.get("expires_in")
        if isinstance(expires_in, (int, float)):
            expires_at = int(time.time() + float(expires_in))

        stored_payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": token_payload.get("token_type"),
            "id_token": id_token,
            "id_token_claims": id_token_claims,
        }
        self._token_manager.set_token(self._service_name, json.dumps(stored_payload, ensure_ascii=False))

    def _extract_access_token(self, stored: str) -> str | None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        expires_at = payload.get("expires_at")
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

    def _ensure_chatgpt_account_id(self, stored: str) -> None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return

        claims = payload.get("id_token_claims")
        if isinstance(claims, dict):
            self._update_chatgpt_account_id(claims)
            return

        id_token = payload.get("id_token")
        if isinstance(id_token, str):
            claims = self._decode_id_token(id_token)
            self._update_chatgpt_account_id(claims)
            payload["id_token_claims"] = claims
            self._token_manager.set_token(self._service_name, json.dumps(payload, ensure_ascii=False))

    def _update_chatgpt_account_id(self, claims: dict[str, Any]) -> None:
        account_id = claims.get("chatgpt_account_id")
        if isinstance(account_id, str):
            self._chatgpt_account_id = account_id
            self._context.extras["chatgpt_account_id"] = account_id

    def _decode_id_token(self, token: str) -> dict[str, Any]:
        try:
            decoded = jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False},
            )
        except Exception:
            return {}

        if not isinstance(decoded, dict):
            return {}
        return decoded

    def _generate_verifier(self) -> str:
        return self._base64_url_encode(secrets.token_bytes(32))

    def _generate_challenge(self, verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        return self._base64_url_encode(digest)

    def _base64_url_encode(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
