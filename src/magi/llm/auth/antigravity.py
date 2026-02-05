"""Antigravity向けOAuth 2.0認証プロバイダ。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
import warnings
import webbrowser

import httpx

from magi.llm.auth.base import AuthContext, AuthProvider
from magi.llm.auth.storage import TokenManager


class AntigravityAuthProvider(AuthProvider):
    """Antigravity向けのOAuth 2.0認証とリフレッシュを管理する。"""

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
        self._token_manager = token_manager or TokenManager()
        self._timeout_seconds = timeout_seconds
        self._service_name = "magi.antigravity"
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[str] | None = None

    async def authenticate(self) -> None:
        """初回認証を行い、トークンを保存する。"""

        if self._context.client_secret:
            token_payload = await self._client_credentials_flow()
        else:
            token_payload = await self._auth_code_flow()
        self._store_tokens(token_payload)

    async def get_token(self) -> str:
        """有効なアクセストークンを返す。必要ならリフレッシュする。"""

        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            await self.authenticate()
            stored = self._token_manager.get_token(self._service_name)

        if not stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")

        token = self._extract_access_token(stored)
        if token is not None:
            return token

        return await self._refresh_queue(stored)

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
            stored = self._token_manager.get_token(self._service_name)
            if not stored:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            token = self._extract_access_token(stored)
            if token is None:
                raise RuntimeError("アクセストークンが取得できませんでした。")
            return token

        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        token = self._extract_access_token(stored)
        if token is None:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        return token

    async def _client_credentials_flow(self) -> dict[str, Any]:
        token_url = self._require_token_url()
        data = {
            "grant_type": "client_credentials",
            "client_id": self._require_client_id(),
            "client_secret": self._context.client_secret,
        }
        if self._context.scopes:
            data["scope"] = " ".join(self._context.scopes)
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        if "access_token" not in payload:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        return payload

    async def _auth_code_flow(self) -> dict[str, Any]:
        auth_url = self._require_auth_url()
        redirect_uri = self._context.redirect_uri
        if not redirect_uri:
            raise RuntimeError("redirect_uriが未設定です。")

        params = {
            "response_type": "code",
            "client_id": self._require_client_id(),
            "redirect_uri": redirect_uri,
        }
        if self._context.scopes:
            params["scope"] = " ".join(self._context.scopes)
        query = httpx.QueryParams(params)
        await asyncio.to_thread(webbrowser.open, f"{auth_url}?{query}")

        raise RuntimeError("認証コードの取得は未実装です。contextにclient_secretがある場合はclient_credentialsを利用してください。")

    async def _refresh_token_flow(self, refresh_token: str) -> dict[str, Any]:
        token_url = self._require_token_url()
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._require_client_id(),
        }
        if self._context.client_secret:
            data["client_secret"] = self._context.client_secret
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        if "access_token" not in payload:
            raise RuntimeError("アクセストークンが取得できませんでした。")
        return payload

    def _store_tokens(self, token_payload: dict[str, Any], refresh_token_fallback: str | None = None) -> None:
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str):
            raise RuntimeError("アクセストークンが取得できませんでした。")

        refresh_token = token_payload.get("refresh_token") or refresh_token_fallback

        expires_at = None
        expires_in = token_payload.get("expires_in")
        if isinstance(expires_in, (int, float)):
            expires_at = int(time.time() + float(expires_in))

        stored_payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": token_payload.get("token_type"),
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

    def _require_client_id(self) -> str:
        if not self._context.client_id:
            raise RuntimeError("client_idが未設定です。")
        return self._context.client_id

    def _require_auth_url(self) -> str:
        if not self._context.auth_url:
            raise RuntimeError("auth_urlが未設定です。")
        return self._context.auth_url

    def _require_token_url(self) -> str:
        if not self._context.token_url:
            raise RuntimeError("token_urlが未設定です。")
        return self._context.token_url
