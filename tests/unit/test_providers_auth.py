import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import os

from magi.core.providers import ProviderContext
from magi.llm.providers_auth import AntigravityAdapter
from magi.llm.client import LLMRequest
from magi.errors import MagiException, ErrorCode


class TestAntigravityAdapter(unittest.TestCase):
    def setUp(self):
        self.context = ProviderContext(
            provider_id="antigravity",
            api_key="fake-key",
            model="gemini-pro",
            options={"project_id": "test-project"},
        )
        self.auth_provider = AsyncMock()
        self.auth_provider.get_token.return_value = "fake-token"

    def test_endpoint_override_logic(self):
        """AntigravityAdapter.ANTIGRAVITY_ENDPOINT が正しく初期化に使用されるか"""
        custom_endpoint = "https://custom.googleapis.com"
        # クラス変数をパッチして、__init__ での反映を確認
        with patch(
            "magi.llm.providers_auth.AntigravityAdapter.ANTIGRAVITY_ENDPOINT",
            custom_endpoint,
        ):
            adapter = AntigravityAdapter(self.context, self.auth_provider)
            self.assertEqual(adapter.endpoint, custom_endpoint)

    @patch("magi.llm.providers_auth.httpx.AsyncClient")
    def test_retry_success(self, mock_client_cls):
        """401エラー後のリトライが成功する場合"""
        client = AsyncMock()
        mock_client_cls.return_value = client

        # 1回目は401, 2回目は200
        response401 = MagicMock()
        response401.status_code = 401

        response200 = MagicMock()
        response200.status_code = 200
        response200.json.return_value = {
            "response": {"candidates": [{"content": {"parts": [{"text": "success"}]}}]}
        }

        client.post.side_effect = [response401, response200]

        adapter = AntigravityAdapter(
            self.context, self.auth_provider, http_client=client
        )
        request = LLMRequest(user_prompt="test", system_prompt="sys")

        result = asyncio.run(adapter.send(request))

        self.assertEqual(result.content, "success")
        self.assertEqual(client.post.await_count, 2)
        # 1回目は通常、2回目はforce_refresh=Trueで呼ばれるはず
        self.assertEqual(self.auth_provider.get_token.await_count, 2)
        self.auth_provider.get_token.assert_called_with(force_refresh=True)

    @patch("magi.llm.providers_auth.httpx.AsyncClient")
    def test_retry_failure_timeout(self, mock_client_cls):
        """401エラー後のリトライでタイムアウトが発生する場合"""
        client = AsyncMock()
        mock_client_cls.return_value = client

        # 1回目は401, 2回目はTimeout
        response401 = MagicMock()
        response401.status_code = 401

        client.post.side_effect = [response401, httpx.TimeoutException("timeout")]

        adapter = AntigravityAdapter(
            self.context, self.auth_provider, http_client=client
        )
        request = LLMRequest(user_prompt="test", system_prompt="sys")

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.API_TIMEOUT.value)
        self.assertEqual(client.post.await_count, 2)

    @patch("magi.llm.providers_auth.httpx.AsyncClient")
    def test_retry_failure_generic(self, mock_client_cls):
        """401エラー後のリトライで一般的なエラーが発生する場合"""
        client = AsyncMock()
        mock_client_cls.return_value = client

        # 1回目は401, 2回目はConnectionError
        response401 = MagicMock()
        response401.status_code = 401

        client.post.side_effect = [response401, Exception("Connection error")]

        adapter = AntigravityAdapter(
            self.context, self.auth_provider, http_client=client
        )
        request = LLMRequest(user_prompt="test", system_prompt="sys")

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.API_ERROR.value)
        self.assertEqual(client.post.await_count, 2)

    @patch("magi.llm.providers_auth.httpx.AsyncClient")
    def test_json_decode_error(self, mock_client_cls):
        client = AsyncMock()
        mock_client_cls.return_value = client

        response200 = MagicMock()
        response200.status_code = 200
        response200.text = "invalid json"
        response200.json.side_effect = ValueError(
            "Expecting value: line 1 column 1 (char 0)"
        )

        client.post.return_value = response200

        adapter = AntigravityAdapter(
            self.context, self.auth_provider, http_client=client
        )
        request = LLMRequest(user_prompt="test", system_prompt="sys")

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.send(request))

        self.assertEqual(exc.exception.error.code, ErrorCode.API_ERROR.value)
        self.assertIn("Failed to parse API response", exc.exception.error.message)

        client = AsyncMock()
        mock_client_cls.return_value = client

        response200 = MagicMock()
        response200.status_code = 200
        response200.json.return_value = {
            "response": {
                "candidates": [{"content": {"parts": [{"text": "success"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 50,
                },
            }
        }

        client.post.return_value = response200

        adapter = AntigravityAdapter(
            self.context, self.auth_provider, http_client=client
        )
        request = LLMRequest(user_prompt="test", system_prompt="sys")

        result = asyncio.run(adapter.send(request))

        self.assertEqual(result.content, "success")
        self.assertEqual(result.usage["input_tokens"], 100)
        self.assertEqual(result.usage["output_tokens"], 50)
