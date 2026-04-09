"""
プロバイダ別のLLMアダプタ
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Protocol

from magi.errors import ErrorCode, MagiError, MagiException, create_api_error
from magi.llm.client import LLMClient, LLMRequest, LLMResponse

if TYPE_CHECKING:
    from magi.core.concurrency import ConcurrencyController
    from magi.core.providers import ProviderContext


def _require_httpx():
    """httpx が必要な場合のみ遅延インポート"""
    try:
        import httpx as _httpx
    except ImportError as exc:
        raise MagiException(
            MagiError(
                code=ErrorCode.CONFIG_INVALID_VALUE.value,
                message="httpx が見つかりません。OpenAI/Gemini プロバイダを使用するには httpx をインストールしてください。",
                details={"dependency": "httpx"},
                recoverable=False,
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
        *,
        llm_client: Optional[LLMClient] = None,
        concurrency_controller: Optional[ConcurrencyController] = None,
    ) -> None:
        self.context = context
        self.provider_id = context.provider_id
        self.model = context.model
        # リソースリークを防ぐため、所有権を追跡
        # llm_client が提供されない場合のみ、内部で LLMClient を作成
        self._owns_client = llm_client is None
        self._llm_client = llm_client or LLMClient(
            api_key=context.api_key,
            model=context.model,
            concurrency_controller=concurrency_controller,
        )

    async def send(self, request: LLMRequest) -> LLMResponse:
        """LLMClientに委譲してメッセージ送信"""
        return await self._llm_client.send(request)

    @property
    def temperature(self) -> float:
        """temperature プロパティ"""
        return self._llm_client.temperature

    async def health(self) -> HealthStatus:
        """課金回避のためデフォルトでスキップ"""
        return HealthStatus(
            provider=self.provider_id,
            ok=False,
            skipped=True,
            reason="healthcheck is opt-in for anthropic",
        )

    async def close(self) -> None:
        """生成した LLMClient をクリーンアップ"""
        if self._owns_client and self._llm_client is not None:
            await self._llm_client.close()

    async def __aenter__(self) -> "AnthropicAdapter":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()


class OpenAIAdapter:
    """OpenAI 向けアダプタ (Chat Completions)"""

    def __init__(
        self,
        context: ProviderContext,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
        chat_endpoint: str = "/v1/chat/completions",
    ) -> None:
        self.context = context
        self.provider_id = context.provider_id
        self.model = context.model
        self.endpoint = (context.endpoint or "https://api.openai.com").rstrip("/")
        self._timeout = timeout
        self._chat_endpoint = chat_endpoint
        self._httpx = _require_httpx()
        self._owns_client = http_client is None
        
        # SSL検証の制御
        verify_ssl = context.options.get("verify_ssl", True)
        if isinstance(verify_ssl, str):
            verify_ssl = verify_ssl.lower() not in ("false", "0", "no")
            
        self._client = http_client or self._httpx.AsyncClient(timeout=timeout, verify=verify_ssl)
        self._validate_required_fields(["api_key", "model"])

    @property
    def temperature(self) -> float:
        """temperature プロパティ"""
        return float(self.context.options.get("temperature", 0.7))

    def _validate_prompts(self, request: LLMRequest) -> None:
        """プロンプトが非空文字列であることを検証"""
        if (
            not request.system_prompt
            or not isinstance(request.system_prompt, str)
            or not request.system_prompt.strip()
        ):
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message="system_prompt must be a non-empty string",
                    details={
                        "provider": self.provider_id,
                        "value": request.system_prompt,
                    },
                    recoverable=False,
                )
            )
        if (
            not request.user_prompt
            or not isinstance(request.user_prompt, str)
            or not request.user_prompt.strip()
        ):
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message="user_prompt must be a non-empty string",
                    details={
                        "provider": self.provider_id,
                        "value": request.user_prompt,
                    },
                    recoverable=False,
                )
            )

    async def send(self, request: LLMRequest) -> LLMResponse:
        """Chat Completions エンドポイントへ送信"""
        import base64

        self._validate_prompts(request)

        # user messageのcontentを構築: テキスト + 添付ファイル
        user_content = [{"type": "text", "text": request.user_prompt}]

        # 添付ファイルがある場合、image_url content partとして追加
        if request.attachments:
            for attachment in request.attachments:
                # base64エンコードしてdata URL形式で追加
                encoded_data = base64.b64encode(attachment.data).decode("utf-8")
                data_url = f"data:{attachment.mime_type};base64,{encoded_data}"
                user_content.append(
                    {"type": "image_url", "image_url": {"url": data_url}}
                )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        # content 形式の決定 (既定はマルチパートだが、options.use_plain_text があれば文字列にする)
        use_plain_text = self.context.options.get("use_plain_text", False)
        
        if use_plain_text:
            payload["messages"].append({"role": "user", "content": request.user_prompt})
        else:
            payload["messages"].append({"role": "user", "content": user_content})

        url = f"{self.endpoint}{self._chat_endpoint}"
        
        # エンドポイントの決定
        endpoint_suffix = self.context.options.get("endpoint_suffix")
        if self.context.options.get("raw_endpoint", False):
            url = self.endpoint
        elif endpoint_suffix:
            url = f"{self.endpoint}{endpoint_suffix}"
            
        logger.info(f"Calling LLM: provider={self.provider_id}, url={url.split('?')[0]}")

        try:
            response = await self._client.post(
                url,
                headers=self._all_headers(),
                json=payload,
                timeout=self._timeout,
            )
        except self._httpx.TimeoutException as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_TIMEOUT,
                    message="OpenAI API リクエストがタイムアウトしました。",
                    details={"provider": self.provider_id},
                    recoverable=True,
                )
            ) from exc
        except self._httpx.HTTPError as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_ERROR,
                    message="OpenAI API 呼び出しでエラーが発生しました。",
                    details={"provider": self.provider_id},
                    recoverable=True,
                )
            ) from exc
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
        try:
            response = await self._client.get(
                url,
                headers=self._auth_headers(),
                timeout=self._timeout,
            )
        except self._httpx.TimeoutException as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_TIMEOUT,
                    message="OpenAI API リクエストがタイムアウトしました。",
                    details={"provider": self.provider_id},
                    recoverable=True,
                )
            ) from exc
        except self._httpx.HTTPError as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_ERROR,
                    message="OpenAI API 呼び出しでエラーが発生しました。",
                    details={"provider": self.provider_id},
                    recoverable=True,
                )
            ) from exc
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
        # options に基づいて認証ヘッダーを選択
        auth_type = self.context.options.get("auth_type", "bearer")
        
        if auth_type == "api-key" or self.context.options.get("use_api_key_header", False):
            return {"api-key": self.context.api_key}
        if auth_type == "x-api-key":
            return {"x-api-key": self.context.api_key}
            
        return {"Authorization": f"Bearer {self.context.api_key}"}

    def _all_headers(self) -> Dict[str, str]:
        """認証ヘッダーとカスタムヘッダーを統合"""
        headers = self._auth_headers()
        
        # User-Agent を設定 (一部のゲートウェイで必須)
        if "User-Agent" not in headers:
            headers["User-Agent"] = "MAGI-System/1.0"
        
        # options 内の "headers" 辞書があればマージ
        custom_headers = self.context.options.get("headers")
        if isinstance(custom_headers, dict):
            for k, v in custom_headers.items():
                headers[str(k)] = str(v)
                
        return headers

    def _validate_required_fields(self, fields: Iterable[str]) -> None:
        missing = [field for field in fields if not getattr(self.context, field)]
        if missing:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"Provider '{self.provider_id}' is missing required fields: {', '.join(missing)}",
                    details={"provider": self.provider_id, "missing_fields": missing},
                    recoverable=False,
                )
            )

    def _raise_for_status(self, response: Any) -> None:
        if response.status_code in (401, 402, 403):
            message_map = {
                401: "API 認証に失敗しました。APIキーを確認してください。",
                402: "クレジット不足または支払いが必要です。APIの支払い設定を確認してください。",
                403: "API へのアクセスが拒否されました。権限を確認してください。"
            }
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_AUTH_ERROR if response.status_code != 402 else ErrorCode.API_ERROR,
                    message=f"{self.provider_id} {message_map.get(response.status_code)}",
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

        resp_text = getattr(response, "text", "")[:500]
        raise MagiException(
            create_api_error(
                code=ErrorCode.API_ERROR,
                message=f"{self.provider_id} API 呼び出しでエラーが発生しました (HTTP {response.status_code}): {resp_text[:200]}",
                details={
                    "provider": self.provider_id,
                    "model": self.model,
                    "status": response.status_code,
                    "response": resp_text,
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
        self._validate_required_fields(["api_key", "model", "endpoint"])

    @property
    def temperature(self) -> float:
        """temperature プロパティ"""
        return float(self.context.options.get("temperature", 0.7))

    async def send(self, request: LLMRequest) -> LLMResponse:
        """Gemini generateContent API を呼び出す"""
        import base64

        if (
            not request.system_prompt
            or not isinstance(request.system_prompt, str)
            or not request.system_prompt.strip()
        ):
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message="system_prompt must be a non-empty string",
                    details={
                        "provider": self.provider_id,
                        "value": request.system_prompt,
                    },
                    recoverable=False,
                )
            )
        if (
            not request.user_prompt
            or not isinstance(request.user_prompt, str)
            or not request.user_prompt.strip()
        ):
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message="user_prompt must be a non-empty string",
                    details={
                        "provider": self.provider_id,
                        "value": request.user_prompt,
                    },
                    recoverable=False,
                )
            )
        url = f"{self.endpoint}/v1beta/models/{self.model}:generateContent"

        # partsを構築: テキスト + 添付ファイル
        parts = [{"text": request.user_prompt}]

        # 添付ファイルがある場合、inline_dataとして追加
        if request.attachments:
            for attachment in request.attachments:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": attachment.mime_type,
                            "data": base64.b64encode(attachment.data).decode("utf-8"),
                        }
                    }
                )

        payload = {
            "contents": [{"parts": parts}],
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }

        try:
            response = await self._client.post(
                url,
                params={"key": self.context.api_key},
                json=payload,
                timeout=self._timeout,
            )
        except self._httpx.TimeoutException as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_TIMEOUT,
                    message="Gemini API リクエストがタイムアウトしました。",
                    details={"provider": self.provider_id},
                    recoverable=True,
                )
            ) from exc
        except self._httpx.HTTPError as exc:
            raise MagiException(
                create_api_error(
                    code=ErrorCode.API_ERROR,
                    message="Gemini API 呼び出しでエラーが発生しました。",
                    details={"provider": self.provider_id},
                    recoverable=True,
                )
            ) from exc
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
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"Provider '{self.provider_id}' is missing required fields: {', '.join(missing)}",
                    details={"provider": self.provider_id, "missing_fields": missing},
                    recoverable=False,
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

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()


class OpenRouterAdapter(OpenAIAdapter):
    """OpenRouter 向けアダプタ (OpenAI 互換 API)"""

    def __init__(
        self,
        context: ProviderContext,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
        chat_endpoint: str = "/chat/completions",
    ) -> None:
        # コンテキストにエンドポイントがない場合は OpenRouter の既定値を使用
        endpoint = context.endpoint or "https://openrouter.ai/api/v1"

        # 親クラスの初期化。context自体は変更せずに値を渡す
        super().__init__(
            context,
            http_client=http_client,
            timeout=timeout,
            chat_endpoint=chat_endpoint,
        )
        # OpenAIAdapter が self.endpoint を context.endpoint から設定している可能性があるため、
        # 確実に上書きする (または super 呼び出し前に context を一時的に変更して戻す)
        self.endpoint = endpoint

    def _auth_headers(self) -> Dict[str, str]:
        headers = super()._auth_headers()
        # OpenRouter 推奨の追加ヘッダー
        # https://openrouter.ai/docs#headers
        headers["HTTP-Referer"] = self.context.options.get(
            "referer", "https://github.com/yohi/magi-core"
        )
        headers["X-Title"] = self.context.options.get("title", "MAGI System")
        return headers


class FlixaAdapter(OpenAIAdapter):
    """Flixa 向けアダプタ (OpenAI 互換 + Open Responses API)"""

    def __init__(
        self,
        context: ProviderContext,
        *,
        http_client: Optional[Any] = None,
        timeout: float = 30.0,
        chat_endpoint: str = "/responses",
    ) -> None:
        # コンテキストにエンドポイントがない場合は Flixa の既定値を使用
        endpoint = context.endpoint or "https://api.flixa.engineer/v1/agent"

        super().__init__(
            context,
            http_client=http_client,
            timeout=timeout,
            chat_endpoint=chat_endpoint,
        )
        self.endpoint = endpoint

    async def send(self, request: LLMRequest) -> LLMResponse:
        """Chat Completions または Open Responses エンドポイントへ送信し、結果をパースする"""
        # 親クラスの send を呼び出す
        response = await super().send(request)
        
        # もし結果が空の場合、Flixa 独自のレスポンス形式（Open Responses）をパースしてみる
        # (親クラスの send は httpx レスポンスを json() して choices を探すが、
        # 見つからない場合は content="" で LLMResponse を返す)
        if not response.content:
            # 再パースのために生のレスポンスデータを取得したいが、LLMResponse には含まれていない
            # そのため、このメソッドでロジックを再実装するか、親クラスを拡張する必要がある。
            # ここではシンプルに、Flixa 向けに send をオーバーライドする。
            return await self._send_flixa(request)
            
        return response

    async def _send_flixa(self, request: LLMRequest) -> LLMResponse:
        """Flixa (Open Responses) 形式での送信とパース"""
        import base64
        self._validate_prompts(request)

        user_content = [{"type": "text", "text": request.user_prompt}]
        if request.attachments:
            for attachment in request.attachments:
                encoded_data = base64.b64encode(attachment.data).decode("utf-8")
                data_url = f"data:{attachment.mime_type};base64,{encoded_data}"
                user_content.append({"type": "image_url", "image_url": {"url": data_url}})

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        # エンドポイントの決定 (既定は /responses)
        endpoint_suffix = self.context.options.get("endpoint_suffix", self._chat_endpoint)
        if self.context.options.get("raw_endpoint", False):
            url = self.endpoint
        else:
            url = f"{self.endpoint}{endpoint_suffix}"

        try:
            resp = await self._client.post(
                url,
                headers=self._all_headers(),
                json=payload,
                timeout=self._timeout,
            )
            self._raise_for_status(resp)
            data = resp.json()
            
            # OpenAI 形式 (choices) のチェック
            content = ""
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {})
                content = str(msg.get("content") or "")
            
            # Flixa (Open Responses) 形式 (output_text) のチェック
            if not content:
                content = str(data.get("output_text") or "")
                
            # それでも空なら output 配列をチェック (flixa-cli のロジック)
            if not content and isinstance(data.get("output"), list):
                segments = []
                for item in data["output"]:
                    if item.get("type") in ["message", "output"]:
                        for c in item.get("content", []):
                            if c.get("text"): segments.append(c["text"])
                content = "\n\n".join(segments)

            usage = data.get("usage") or {}
            return LLMResponse(
                content=content,
                usage={
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
                model=data.get("model") or self.model,
            )
        except Exception as e:
            if isinstance(e, MagiException): raise
            raise create_api_error(
                code=ErrorCode.API_ERROR,
                message=f"Flixa API error: {str(e)}",
                details={"provider": self.provider_id},
                recoverable=True
            ) from e
