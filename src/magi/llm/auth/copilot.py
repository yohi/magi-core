"""GitHub Copilot Device Flow 認証プロバイダ。"""

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

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

DEFAULT_CLIENT_ID = "Iv1.b507a08c87ecfe98"

DEFAULT_HEADERS = {
    "User-Agent": "magi/llm-auth",
    "Editor-Version": "vscode/1.85.0",
    "Copilot-Integration-Id": "vscode-chat",
    "Editor-Plugin-Version": "copilot-chat/0.12.0",
}


class CopilotAuthProvider(AuthProvider):
    """GitHub Copilot向けのDevice Flow認証を行う。"""

    def __init__(
        self,
        context: AuthContext,
        token_manager: TokenManager | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        """CopilotAuthProviderを初期化する。

        Args:
            context: 認証に必要な設定情報。
            token_manager: トークン保存先。
            timeout_seconds: デバイスフローのポーリング上限。
        """

        self._context = context
        self._token_manager = token_manager or TokenManager()
        self._timeout_seconds = timeout_seconds
        self._service_name = "magi.copilot"

    async def authenticate(self) -> None:
        """Device Flowを実行し、Copilotトークンを保存する。"""

        device_code_info = await self._request_device_code()
        await self._prompt_user(device_code_info)

        github_token = await self._poll_for_github_token(device_code_info)
        copilot_payload = await self._fetch_copilot_token(github_token)
        self._store_tokens(github_token, copilot_payload)

    async def get_token(self) -> str:
        """Copilotトークンを返す。期限切れなら更新する。"""

        stored = self._token_manager.get_token(self._service_name)
        if stored:
            token_value = self._extract_copilot_token(stored)
            if token_value is not None:
                return token_value

            github_token = self._extract_github_token(stored)
            if github_token:
                try:
                    copilot_payload = await self._fetch_copilot_token(github_token)
                    self._store_tokens(github_token, copilot_payload)
                    token_value = copilot_payload.get("token")
                    if isinstance(token_value, str):
                        return token_value
                except httpx.HTTPStatusError:
                    warnings.warn(
                        "Copilotトークン更新に失敗したため再認証します。",
                        RuntimeWarning,
                        stacklevel=2,
                    )

        await self.authenticate()
        stored = self._token_manager.get_token(self._service_name)
        if not stored:
            raise RuntimeError("Copilotトークンが取得できませんでした。")

        token_value = self._extract_copilot_token(stored)
        if token_value is None:
            raise RuntimeError("Copilotトークンが取得できませんでした。")
        return token_value

    async def _request_device_code(self) -> dict[str, Any]:
        client_id = self._context.client_id or DEFAULT_CLIENT_ID
        scopes = self._context.scopes or ["read:user"]
        data = {
            "client_id": client_id,
            "scope": " ".join(scopes),
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GITHUB_DEVICE_CODE_URL,
                data=data,
                headers={"Accept": "application/json", **DEFAULT_HEADERS},
            )
        response.raise_for_status()
        payload = response.json()
        if "device_code" not in payload:
            raise RuntimeError("device_codeが取得できませんでした。")
        return payload

    async def _prompt_user(self, device_info: dict[str, Any]) -> None:
        user_code = device_info.get("user_code")
        verification_uri = device_info.get("verification_uri")
        if not user_code or not verification_uri:
            raise RuntimeError("認証コード情報が不足しています。")

        await asyncio.to_thread(self._copy_to_clipboard, str(user_code))
        await asyncio.to_thread(webbrowser.open, str(verification_uri))

        print("GitHub Copilotの認証を完了してください。")
        print(f"コード: {user_code}")
        print(f"URL: {verification_uri}")

    async def _poll_for_github_token(self, device_info: dict[str, Any]) -> str:
        device_code = device_info.get("device_code")
        if not device_code:
            raise RuntimeError("device_codeが不足しています。")

        interval = int(device_info.get("interval", 5))
        expires_in = int(device_info.get("expires_in", self._timeout_seconds))
        deadline = time.time() + min(expires_in, self._timeout_seconds)

        client_id = self._context.client_id or DEFAULT_CLIENT_ID
        data = {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }

        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                response = await client.post(
                    GITHUB_TOKEN_URL,
                    data=data,
                    headers={"Accept": "application/json", **DEFAULT_HEADERS},
                )
                response.raise_for_status()
                payload = response.json()

                if "access_token" in payload:
                    return str(payload["access_token"])

                error = payload.get("error")
                if error == "authorization_pending":
                    await asyncio.sleep(interval)
                    continue
                if error == "slow_down":
                    interval += 5
                    await asyncio.sleep(interval)
                    continue
                if error in {"expired_token", "access_denied"}:
                    raise RuntimeError("デバイス認証が失敗しました。")

                raise RuntimeError(f"デバイス認証に失敗しました: {error}")

        raise TimeoutError("デバイス認証がタイムアウトしました。")

    async def _fetch_copilot_token(self, github_token: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {github_token}",
            **DEFAULT_HEADERS,
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(COPILOT_TOKEN_URL, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if "token" not in payload:
            raise RuntimeError("Copilotトークンが取得できませんでした。")
        return payload

    def _store_tokens(self, github_token: str, copilot_payload: dict[str, Any]) -> None:
        token = copilot_payload.get("token")
        if not isinstance(token, str):
            raise RuntimeError("Copilotトークンが取得できませんでした。")

        expires_at = copilot_payload.get("expires_at")
        if isinstance(expires_at, str):
            try:
                expires_at = int(float(expires_at))
            except ValueError:
                expires_at = None
        if isinstance(expires_at, (int, float)):
            expires_at = int(expires_at)

        stored_payload = {
            "github_token": github_token,
            "copilot_token": token,
            "copilot_expires_at": expires_at,
            "token_type": copilot_payload.get("token_type"),
        }
        self._token_manager.set_token(self._service_name, json.dumps(stored_payload, ensure_ascii=False))

    def _extract_copilot_token(self, stored: str) -> str | None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        expires_at = payload.get("copilot_expires_at")
        if isinstance(expires_at, (int, float)) and time.time() >= float(expires_at):
            return None

        token = payload.get("copilot_token")
        if isinstance(token, str):
            return token
        return None

    def _extract_github_token(self, stored: str) -> str | None:
        try:
            payload = json.loads(stored)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        token = payload.get("github_token")
        if isinstance(token, str):
            return token
        return None

    def _copy_to_clipboard(self, code: str) -> None:
        try:
            import pyperclip
        except Exception:
            return

        try:
            pyperclip.copy(code)
        except Exception:
            return
