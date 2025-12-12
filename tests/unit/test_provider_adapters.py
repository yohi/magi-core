"""
ProviderAdapter 実装のユニットテスト
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

from magi.core.providers import ProviderContext
from magi.errors import ErrorCode, MagiException
from magi.llm.client import LLMRequest, LLMResponse
from magi.llm.providers import (
    AnthropicAdapter,
    GeminiAdapter,
    HealthStatus,
    OpenAIAdapter,
)


class DummyLLMClient:
    """sendのみを持つ簡易モック"""

    def __init__(self, response: LLMResponse):
        self.response = response
        self.calls = []

    async def send(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return self.response


class TestAnthropicAdapter(unittest.TestCase):
    """AnthropicAdapterのテスト"""

    def test_health_is_skipped_by_default(self):
        """課金回避のためヘルスチェックは既定でスキップする"""
        ctx = ProviderContext(
            provider_id="anthropic",
            api_key="key",
            model="claude-3",
        )
        adapter = AnthropicAdapter(ctx, llm_client=DummyLLMClient(LLMResponse("ok", {"input_tokens": 1, "output_tokens": 1}, "claude-3")))

        status = asyncio.run(adapter.health())

        self.assertIsInstance(status, HealthStatus)
        self.assertTrue(status.skipped)
        self.assertFalse(status.ok)
        self.assertEqual(status.provider, "anthropic")

    def test_send_delegates_to_llm_client(self):
        """LLMClientへの委譲でレスポンスを返す"""
        ctx = ProviderContext(
            provider_id="anthropic",
            api_key="key",
            model="claude-3",
        )
        response = LLMResponse(
            content="delegated",
            usage={"input_tokens": 10, "output_tokens": 5},
            model="claude-3",
        )
        llm_client = DummyLLMClient(response)
        adapter = AnthropicAdapter(ctx, llm_client=llm_client)
        request = LLMRequest(system_prompt="sys", user_prompt="hello", max_tokens=32, temperature=0.1)

        result = asyncio.run(adapter.send(request))

        self.assertEqual(result.content, "delegated")
        self.assertEqual(llm_client.calls[0].user_prompt, "hello")
        self.assertEqual(llm_client.calls[0].max_tokens, 32)


class TestOpenAIAdapter(unittest.TestCase):
    """OpenAIAdapterのテスト"""

    def test_health_calls_models_endpoint(self):
        """非課金の/v1/modelsでヘルスチェックする"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )
        http_client = AsyncMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": [{"id": "gpt-4o"}]}
        http_client.get.return_value = response
        adapter = OpenAIAdapter(ctx, http_client=http_client)

        status = asyncio.run(adapter.health())

        http_client.get.assert_awaited_once()
        self.assertTrue(status.ok)
        self.assertFalse(status.skipped)
        self.assertEqual(status.provider, "openai")
        self.assertIn("gpt-4o", status.details.get("models", []))

    def test_health_raises_on_auth_error_without_retry(self):
        """認証失敗はリトライせずMagiExceptionを返す"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="invalid",
            model="gpt-4o-mini",
        )
        http_client = AsyncMock()
        response = MagicMock()
        response.status_code = 401
        response.text = "Unauthorized"
        http_client.get.return_value = response
        adapter = OpenAIAdapter(ctx, http_client=http_client)

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.health())

        self.assertEqual(http_client.get.await_count, 1)
        self.assertEqual(exc.exception.error.code, ErrorCode.API_AUTH_ERROR.value)
        self.assertFalse(exc.exception.error.recoverable)

    def test_send_builds_chat_completion_payload(self):
        """Chat Completions経由でレスポンスを正規化する"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )
        http_client = AsyncMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "model": "gpt-4o",
        }
        http_client.post.return_value = response
        adapter = OpenAIAdapter(ctx, http_client=http_client)
        request = LLMRequest(
            system_prompt="sys",
            user_prompt="hi",
            max_tokens=64,
            temperature=0.2,
        )

        result = asyncio.run(adapter.send(request))

        http_client.post.assert_awaited_once()
        self.assertEqual(result.content, "hello")
        self.assertEqual(result.usage["input_tokens"], 5)
        self.assertEqual(result.usage["output_tokens"], 3)
        self.assertEqual(result.model, "gpt-4o")

    def test_openai_prompt_validation_raises_magi_exception(self):
        """空プロンプトでMagiException(CONFIG_INVALID_VALUE)を返す"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )
        adapter = OpenAIAdapter(ctx, http_client=AsyncMock())
        request = LLMRequest(system_prompt=" ", user_prompt="hello")

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.CONFIG_INVALID_VALUE.value)

    def test_openai_timeout_maps_to_api_timeout(self):
        """httpx Timeout を API_TIMEOUT に正規化する"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )

        class DummyHttpx:
            class TimeoutException(Exception):
                pass

            class HTTPError(Exception):
                pass

        http_client = AsyncMock()
        http_client.post.side_effect = DummyHttpx.TimeoutException("timeout")

        with patch("magi.llm.providers._require_httpx", return_value=DummyHttpx()):
            adapter = OpenAIAdapter(ctx, http_client=http_client)

        request = LLMRequest(system_prompt="sys", user_prompt="u")
        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.API_TIMEOUT.value)
        self.assertEqual(http_client.post.await_count, 1)

    def test_openai_adapter_closes_owned_client(self):
        """内部生成したクライアントのみをcloseする"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )

        owned_client = AsyncMock()

        class DummyHttpx:
            def __init__(self, client):
                self.client = client

            def AsyncClient(self, *_, **__):
                return self.client

        with patch("magi.llm.providers._require_httpx", return_value=DummyHttpx(owned_client)):
            adapter = OpenAIAdapter(ctx)
        asyncio.run(adapter.close())

        owned_client.aclose.assert_awaited_once()

        injected = AsyncMock()
        adapter2 = OpenAIAdapter(ctx, http_client=injected)
        asyncio.run(adapter2.close())
        injected.aclose.assert_not_called()

    def test_openai_health_timeout_maps_to_api_timeout(self):
        """health() での Timeout を API_TIMEOUT に正規化する"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )

        class DummyHttpx:
            class TimeoutException(Exception):
                pass

            class HTTPError(Exception):
                pass

        http_client = AsyncMock()
        http_client.get.side_effect = DummyHttpx.TimeoutException("timeout")

        with patch("magi.llm.providers._require_httpx", return_value=DummyHttpx()):
            adapter = OpenAIAdapter(ctx, http_client=http_client)

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.health())

        self.assertEqual(exc.exception.error.code, ErrorCode.API_TIMEOUT.value)
        self.assertEqual(http_client.get.await_count, 1)

    def test_openai_health_http_error_maps_to_api_error(self):
        """health() での HTTPError を API_ERROR に正規化する"""
        ctx = ProviderContext(
            provider_id="openai",
            api_key="openai-key",
            model="gpt-4o",
        )

        class DummyHttpx:
            class TimeoutException(Exception):
                pass

            class HTTPError(Exception):
                pass

        http_client = AsyncMock()
        http_client.get.side_effect = DummyHttpx.HTTPError("conn failed")

        with patch("magi.llm.providers._require_httpx", return_value=DummyHttpx()):
            adapter = OpenAIAdapter(ctx, http_client=http_client)

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.health())

        self.assertEqual(exc.exception.error.code, ErrorCode.API_ERROR.value)
        self.assertEqual(http_client.get.await_count, 1)


class TestGeminiAdapter(unittest.TestCase):
    """GeminiAdapterのテスト"""

    def test_missing_endpoint_is_reported(self):
        """エンドポイントが未指定なら明示エラー"""
        ctx = ProviderContext(
            provider_id="gemini",
            api_key="gem-key",
            model="gemini-1.5",
            endpoint=None,
        )
        with self.assertRaises(MagiException) as exc:
            GeminiAdapter(ctx)

        details = exc.exception.error.details or {}
        self.assertIn("endpoint", details.get("missing_fields", []))

    def test_gemini_prompt_validation_raises_magi_exception(self):
        """空プロンプトでMagiException(CONFIG_INVALID_VALUE)を返す"""
        ctx = ProviderContext(
            provider_id="gemini",
            api_key="gem-key",
            model="gemini-1.5",
            endpoint="https://example.com",
        )
        adapter = GeminiAdapter(ctx, http_client=AsyncMock())
        request = LLMRequest(system_prompt="", user_prompt="hi")

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.CONFIG_INVALID_VALUE.value)

    def test_gemini_timeout_maps_to_api_timeout(self):
        """httpx Timeout を API_TIMEOUT に正規化する"""
        ctx = ProviderContext(
            provider_id="gemini",
            api_key="gem-key",
            model="gemini-1.5",
            endpoint="https://example.com",
        )

        class DummyHttpx:
            class TimeoutException(Exception):
                pass

            class HTTPError(Exception):
                pass

        http_client = AsyncMock()
        http_client.post.side_effect = DummyHttpx.TimeoutException("timeout")

        with patch("magi.llm.providers._require_httpx", return_value=DummyHttpx()):
            adapter = GeminiAdapter(ctx, http_client=http_client)

        request = LLMRequest(system_prompt="sys", user_prompt="u")
        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.API_TIMEOUT.value)

    def test_health_is_skipped_by_default(self):
        """課金回避のためヘルスチェックは既定でスキップする"""
        ctx = ProviderContext(
            provider_id="gemini",
            api_key="gem-key",
            model="gemini-1.5",
            endpoint="https://generativelanguage.googleapis.com",
        )
        adapter = GeminiAdapter(ctx)

        status = asyncio.run(adapter.health())

        self.assertTrue(status.skipped)
        self.assertFalse(status.ok)
        self.assertEqual(status.provider, "gemini")


if __name__ == "__main__":
    unittest.main()
