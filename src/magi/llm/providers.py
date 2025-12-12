"""
プロバイダ別のLLMアダプタ
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Protocol

from magi.errors import ErrorCode, MagiError, MagiException, create_api_error, create_config_error
from magi.llm.client import LLMClient, LLMRequest, LLMResponse

if TYPE_CHECKING:
    from magi.core.providers import ProviderContext


def _require_httpx():
    """httpx が必要な場合のみ遅延インポート"""
    try:
        import httpx as _httpx
    except ImportError as exc:
        raise MagiException(
            create_config_error(
                "httpx が見つかりません。OpenAI/Gemini プロバイダを使用するには httpx をインストールしてください。",
                details={"dependency": "httpx"},
            )
        ) from exc
    return _httpx


@dataclass
class HealthStatus:
    """ヘルスチェック結果"""

    provider: str
    ok: bool
    skipped: bool = False
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    """プロバイダアダプタ共通インターフェース"""

    provider_id: str
    model: str

    async def send(self, request: LLMRequest) -> LLMResponse: ...

    async def health(self) -> HealthStatus: ...


class AnthropicAdapter:
    """Anthropic 向けアダプタ"""

    def __init__(
        self,
        context: ProviderContext,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self.context = context
        self.provider_id = context.provider_id
        self.model = context.model
        self._llm_client = llm_client or LLMClient(
            api_key=context.api_key,
            model=context.model,
        )

    async def send(self, request: LLMRequest) -> LLMResponse:
        """LLMClientに委譲してメッセージ送信"""
        return await self._llm_client.send(request)

    async def health(self) -> HealthStatus:
        """課金回避のためデフォルトでスキップ"""
        return HealthStatus(
            provider=self.provider_id,
            ok=False,
            skipped=True,
            reason="healthcheck is opt-in for anthropic",
        )


class OpenAIAdapter:
    """OpenAI 向けアダプタ (Chat Completions)"""

    def __init__(
        self,
        context: ProviderContext,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
    ) -> None:
        self.context = context
        self.provider_id = context.provider_id
        self.model = context.model
        self.endpoint = (context.endpoint or "https://api.openai.com").rstrip("/")
        self._timeout = timeout
        self._httpx = _require_httpx()
        self._owns_client = http_client is None
        self._client = http_client or self._httpx.AsyncClient(timeout=timeout)
        self._validate_required_fields(["api_key", "model"])

    async def send(self, request: LLMRequest) -> LLMResponse:
        """Chat Completions エンドポイントへ送信"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        url = f"{self.endpoint}/v1/chat/completions"
        response = await self._client.post(
            url,
            headers=self._auth_headers(),
            json=payload,
            timeout=self._timeout,
        )
        self._raise_for_status(response)
        data = response.json()

        content = ""
        if isinstance(data.get("choices"), Iterable):
            first = next(iter(data["choices"]), None)
            if first and isinstance(first, dict):
                message = first.get("message") or {}
                if isinstance(message, dict):
                    content = str(message.get("content") or "")

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
            model=data.get("model") or self.model,
        )

    async def health(self) -> HealthStatus:
        """非課金の /v1/models で疎通確認"""
        url = f"{self.endpoint}/v1/models"
        response = await self._client.get(
            url,
            headers=self._auth_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status(response)
        data = response.json() if hasattr(response, "json") else {}
        models = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            models = [m.get("id") for m in data["data"] if isinstance(m, dict)]

        return HealthStatus(
            provider=self.provider_id,
            ok=True,
            skipped=False,
            details={"models": models},
        )

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.context.api_key}"}

    def _validate_required_fields(self, fields: Iterable[str]) -> None:
        missing = [field for field in fields if not getattr(self.context, field)]
        if missing:
            raise MagiException(
                create_config_error(
                    f"Provider '{self.provider_id}' is missing required fields: {', '.join(missing)}",
                    details={"provider": self.provider_id, "missing_fields": missing},
                )
            )

    def _raise_for_status(self, response: Any) -> None:
        if response.status_code in (401, 403):
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_AUTH_ERROR,
                    message="OpenAI API 認証に失敗しました。APIキーを確認してください。",
                    details={
                        "provider": self.provider_id,
                        "status": response.status_code,
                        "response": getattr(response, "text", "")[:200],
                    },
                    recoverable=False,
                )
            )
        if 200 <= response.status_code < 300:
            return

        raise MagiException(
            create_api_error(
                code=ErrorCode.API_ERROR,
                message="OpenAI API 呼び出しでエラーが発生しました。",
                details={
                    "provider": self.provider_id,
                    "status": response.status_code,
                    "response": getattr(response, "text", "")[:200],
                },
                recoverable=True,
            )
        )

    async def close(self) -> None:
        """生成した httpx クライアントをクリーンアップ"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> "OpenAIAdapter":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()


class GeminiAdapter:
    """Gemini 向けアダプタ"""

    def __init__(
        self,
        context: ProviderContext,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
    ) -> None:
        self.context = context
        self.provider_id = context.provider_id
        self.model = context.model
        self.endpoint = (context.endpoint or "").rstrip("/")
        self._timeout = timeout
        self._httpx = _require_httpx()
        # リソースリークを防ぐため、所有権を追跡
        # http_client が提供されない場合のみ、内部で httpx.AsyncClient を作成
        self._owns_client = http_client is None
        self._client = http_client or self._httpx.AsyncClient(timeout=timeout)
        self._validate_required_fields(["api_key", "model"])

    async def send(self, request: LLMRequest) -> LLMResponse:
        """Gemini generateContent API を呼び出す"""
        if not self.endpoint:
            raise MagiException(
                create_config_error(
                    "Gemini endpoint is required.",
                    details={"provider": self.provider_id, "missing_fields": ["endpoint"]},
                )
            )

        url = f"{self.endpoint}/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": request.user_prompt},
                    ]
                }
            ],
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }

        response = await self._client.post(
            url,
            params={"key": self.context.api_key},
            json=payload,
            timeout=self._timeout,
        )
        self._raise_for_status(response)
        data = response.json()

        content = self._extract_text(data)
        usage = self._extract_usage(data)

        return LLMResponse(
            content=content,
            usage=usage,
            model=self.model,
        )

    async def health(self) -> HealthStatus:
        """課金経路を避けるためデフォルトでスキップ"""
        return HealthStatus(
            provider=self.provider_id,
            ok=False,
            skipped=True,
            reason="healthcheck is opt-in for gemini",
        )

    def _extract_text(self, data: Dict[str, Any]) -> str:
        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            content = candidate.get("content") if isinstance(candidate, dict) else None
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list) and parts:
                    part = parts[0]
                    if isinstance(part, dict):
                        return str(part.get("text") or "")
        return ""

    def _extract_usage(self, data: Dict[str, Any]) -> Dict[str, int]:
        usage_meta = data.get("usageMetadata") or {}
        return {
            "input_tokens": usage_meta.get("promptTokenCount", 0),
            "output_tokens": usage_meta.get("candidatesTokenCount", 0),
        }

    def _validate_required_fields(self, fields: Iterable[str]) -> None:
        missing = [field for field in fields if not getattr(self.context, field)]
        if missing:
            raise MagiException(
                create_config_error(
                    f"Provider '{self.provider_id}' is missing required fields: {', '.join(missing)}",
                    details={"provider": self.provider_id, "missing_fields": missing},
                )
            )

    def _raise_for_status(self, response: Any) -> None:
        if response.status_code in (401, 403):
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_AUTH_ERROR,
                    message="Gemini API 認証に失敗しました。APIキーを確認してください。",
                    details={
                        "provider": self.provider_id,
                        "status": response.status_code,
                        "response": getattr(response, "text", "")[:200],
                    },
                    recoverable=False,
                )
            )
        if 200 <= response.status_code < 300:
            return
        raise MagiException(
            create_api_error(
                code=ErrorCode.API_ERROR,
                message="Gemini API 呼び出しでエラーが発生しました。",
                details={
                    "provider": self.provider_id,
                    "status": response.status_code,
                    "response": getattr(response, "text", "")[:200],
                },
                recoverable=True,
            )
        )

    async def close(self) -> None:
        """生成した httpx クライアントをクリーンアップ"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> "GeminiAdapter":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()
