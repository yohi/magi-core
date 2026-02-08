"""認証プロバイダを利用するLLMアダプタ。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, TYPE_CHECKING

import httpx

from magi.errors import ErrorCode, MagiException, create_api_error
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
        chat_endpoint: str = "/v1/chat/completions",
    ) -> None:
        if not context.api_key:
            context.api_key = "auth"
        if endpoint_override and not context.endpoint:
            context.endpoint = endpoint_override
        self._auth_provider = auth_provider
        self._extra_headers = extra_headers or {}
        super().__init__(
            context,
            http_client=http_client,
            timeout=timeout,
            chat_endpoint=chat_endpoint,
        )

    @property
    def temperature(self) -> float:
        """temperature プロパティ"""
        return float(self.context.options.get("temperature", 0.7))

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
    """Antigravity向けGoogle Generative Language API アダプタ。"""

    ANTIGRAVITY_VERSION = "1.15.8"
    ANTIGRAVITY_ENDPOINT = os.environ.get(
        "ANTIGRAVITY_ENDPOINT", "https://cloudcode-pa.googleapis.com"
    )

    def __init__(
        self,
        context: ProviderContext,
        auth_provider: AntigravityAuthProvider,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {
            "User-Agent": (
                f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Antigravity/{self.ANTIGRAVITY_VERSION} "
                f"Chrome/138.0.7204.235 Electron/37.3.1 Safari/537.36"
            ),
            "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
            "Client-Metadata": (
                '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED",'
                '"pluginType":"GEMINI"}'
            ),
        }
        super().__init__(
            context,
            auth_provider,
            http_client=http_client,
            timeout=timeout,
            endpoint_override=self.ANTIGRAVITY_ENDPOINT,
            extra_headers=headers,
            chat_endpoint="/v1internal:generateContent",
        )

    def _convert_to_google_format(self, request: LLMRequest) -> Dict[str, Any]:
        """OpenAI形式からAntigravity API形式に変換する。"""
        import base64
        import uuid

        system_instruction = {"parts": [{"text": request.system_prompt}]}
        user_parts = [{"text": request.user_prompt}]

        if request.attachments:
            for attachment in request.attachments:
                encoded_data = base64.b64encode(attachment.data).decode("utf-8")
                user_parts.append(
                    {
                        "inline_data": {
                            "mime_type": attachment.mime_type,
                            "data": encoded_data,
                        }
                    }
                )

        contents = [{"role": "user", "parts": user_parts}]
        generation_config = {
            "maxOutputTokens": request.max_tokens,
            "temperature": request.temperature,
        }

        request_payload = {
            "systemInstruction": system_instruction,
            "contents": contents,
            "generationConfig": generation_config,
        }

        wrapped_body = {
            "project": self.context.options.get("project_id", "rising-fact-p41fc"),
            "model": self.model,
            "request": request_payload,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": f"agent-{uuid.uuid4()}",
        }

        return wrapped_body

    async def send(self, request: LLMRequest) -> LLMResponse:
        """Google Generative Language API形式に変換して送信する。"""

        self._validate_prompts(request)

        payload = self._convert_to_google_format(request)

        token = await self._auth_provider.get_token()
        self.context.api_key = token

        url = f"{self.endpoint}{self._chat_endpoint}"

        try:
            response = await self._client.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_TIMEOUT,
                    message=f"Request to {url} timed out",
                    details={
                        "provider": self.provider_id,
                        "model": self.model,
                        "url": url,
                        "timeout": self._timeout,
                    },
                )
            ) from exc
        except Exception as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_ERROR,
                    message=f"Request to {url} failed: {exc}",
                    details={
                        "provider": self.provider_id,
                        "model": self.model,
                        "url": url,
                        "error": str(exc),
                    },
                )
            ) from exc

        if response.status_code == 401:
            token = await self._auth_provider.get_token(force_refresh=True)
            self.context.api_key = token
            try:
                response = await self._client.post(
                    url,
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                raise MagiException(
                    create_api_error(
                        code=ErrorCode.API_TIMEOUT,
                        message=f"Retry request to {url} timed out",
                        details={
                            "provider": self.provider_id,
                            "model": self.model,
                            "url": url,
                            "timeout": self._timeout,
                        },
                    )
                ) from exc
            except Exception as exc:
                raise MagiException(
                    create_api_error(
                        code=ErrorCode.API_ERROR,
                        message=f"Retry request to {url} failed: {exc}",
                        details={
                            "provider": self.provider_id,
                            "model": self.model,
                            "url": url,
                            "error": str(exc),
                        },
                    )
                ) from exc

        if response.status_code != 200:
            error_text = response.text
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_ERROR,
                    message=f"API request failed with status {response.status_code}",
                    details={
                        "provider": self.provider_id,
                        "model": self.model,
                        "status": response.status_code,
                        "error": error_text,
                        "url": url,
                    },
                )
            )

        data = response.json()

        try:
            response_data = data.get("response", {})
            candidates = response_data.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates in response")

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise ValueError("No parts in content")

            text = parts[0].get("text", "")

            return LLMResponse(
                content=text,
                usage={},
                model=self.model,
            )
        except (KeyError, IndexError, ValueError) as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_ERROR,
                    message=f"Failed to parse API response: {exc}",
                    details={
                        "provider": self.provider_id,
                        "model": self.model,
                        "response": data,
                        "error": str(exc),
                    },
                )
            ) from exc
