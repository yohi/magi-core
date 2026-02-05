"""認証プロバイダを利用するLLMアダプタ。"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from magi.errors import ErrorCode, MagiException
from magi.llm.auth import AntigravityAuthProvider, AuthProvider, CopilotAuthProvider
from magi.llm.client import LLMRequest, LLMResponse
from magi.llm.providers import OpenAIAdapter

if TYPE_CHECKING:
    from magi.core.providers import ProviderContext


class AuthenticatedOpenAIAdapter(OpenAIAdapter):
    """認証プロバイダからトークンを取得して送信するOpenAI互換アダプタ。"""

    def __init__(
        self,
        context: ProviderContext,
        auth_provider: AuthProvider,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
        endpoint_override: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if not context.api_key:
            context.api_key = "auth"
        if endpoint_override and not context.endpoint:
            context.endpoint = endpoint_override
        self._auth_provider = auth_provider
        self._extra_headers = extra_headers or {}
        super().__init__(context, http_client=http_client, timeout=timeout)

    async def send(self, request: LLMRequest) -> LLMResponse:
        """トークンを取得して送信する。"""

        token = await self._auth_provider.get_token()
        self.context.api_key = token
        return await super().send(request)

    def _auth_headers(self) -> Dict[str, str]:
        headers = super()._auth_headers()
        headers.update(self._extra_headers)
        return headers


class CopilotAdapter(AuthenticatedOpenAIAdapter):
    """GitHub Copilot向けのOpenAI互換アダプタ。"""

    def __init__(
        self,
        context: ProviderContext,
        auth_provider: CopilotAuthProvider,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
        endpoint_override: Optional[str] = None,
    ) -> None:
        headers = {
            "Editor-Version": "vscode/1.85.0",
            "Copilot-Integration-Id": "vscode-chat",
        }
        endpoint = endpoint_override or "https://copilot-proxy.githubusercontent.com/v1"
        super().__init__(
            context,
            auth_provider,
            http_client=http_client,
            timeout=timeout,
            endpoint_override=endpoint,
            extra_headers=headers,
        )


class AntigravityAdapter(AuthenticatedOpenAIAdapter):
    """Antigravity向けOpenAI互換アダプタ。"""

    def __init__(
        self,
        context: ProviderContext,
        auth_provider: AntigravityAuthProvider,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(
            context,
            auth_provider,
            http_client=http_client,
            timeout=timeout,
        )

    async def send(self, request: LLMRequest) -> LLMResponse:
        """401時はトークン更新後に再試行する。"""

        try:
            return await super().send(request)
        except MagiException as exc:
            if exc.error.code != ErrorCode.API_AUTH_ERROR.value:
                raise
        token = await self._auth_provider.get_token()
        self.context.api_key = token
        return await super().send(request)
