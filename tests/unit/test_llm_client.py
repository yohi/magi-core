"""LLMクライアントのユニットテスト

LLMクライアントの基本機能をテストする。
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from magi.llm.client import (
    LLMRequest,
    LLMResponse,
    LLMClient,
    APIErrorType,
)
from magi.errors import ErrorCode, MagiError, MagiException


class TestLLMRequest(unittest.TestCase):
    """LLMRequestのテスト"""

    def test_create_with_defaults(self):
        """デフォルト値でのリクエスト作成"""
        request = LLMRequest(
            system_prompt="システムプロンプト",
            user_prompt="ユーザープロンプト"
        )
        self.assertEqual(request.system_prompt, "システムプロンプト")
        self.assertEqual(request.user_prompt, "ユーザープロンプト")
        self.assertEqual(request.max_tokens, 4096)
        self.assertEqual(request.temperature, 0.7)

    def test_create_with_custom_values(self):
        """カスタム値でのリクエスト作成"""
        request = LLMRequest(
            system_prompt="システム",
            user_prompt="ユーザー",
            max_tokens=2048,
            temperature=0.5
        )
        self.assertEqual(request.max_tokens, 2048)
        self.assertEqual(request.temperature, 0.5)


class TestLLMResponse(unittest.TestCase):
    """LLMResponseのテスト"""

    def test_create_response(self):
        """レスポンス作成"""
        response = LLMResponse(
            content="応答内容",
            usage={"input_tokens": 100, "output_tokens": 50},
            model="claude-sonnet-4-20250514"
        )
        self.assertEqual(response.content, "応答内容")
        self.assertEqual(response.usage["input_tokens"], 100)
        self.assertEqual(response.model, "claude-sonnet-4-20250514")


class TestAPIErrorType(unittest.TestCase):
    """APIErrorTypeのテスト"""

    def test_error_type_values(self):
        """エラータイプ値の確認"""
        self.assertEqual(APIErrorType.TIMEOUT.value, "timeout")
        self.assertEqual(APIErrorType.RATE_LIMIT.value, "rate_limit")
        self.assertEqual(APIErrorType.AUTH_ERROR.value, "auth_error")
        self.assertEqual(APIErrorType.UNKNOWN.value, "unknown")


class TestLLMClient(unittest.TestCase):
    """LLMClientのテスト"""

    def test_init_with_defaults(self):
        """デフォルト値での初期化"""
        client = LLMClient(api_key="test-key")
        self.assertEqual(client.api_key, "test-key")
        self.assertEqual(client.model, "claude-sonnet-4-20250514")
        self.assertEqual(client.retry_count, 3)
        self.assertEqual(client.timeout, 60)

    def test_init_with_custom_values(self):
        """カスタム値での初期化"""
        client = LLMClient(
            api_key="test-key",
            model="claude-3-opus-20240229",
            retry_count=5,
            timeout=120
        )
        self.assertEqual(client.model, "claude-3-opus-20240229")
        self.assertEqual(client.retry_count, 5)
        self.assertEqual(client.timeout, 120)

    def test_classify_error_timeout(self):
        """タイムアウトエラーの分類"""
        client = LLMClient(api_key="test-key")

        # asyncio.TimeoutError
        error_type = client._classify_error(asyncio.TimeoutError())
        self.assertEqual(error_type, APIErrorType.TIMEOUT)

        # TimeoutError
        error_type = client._classify_error(TimeoutError())
        self.assertEqual(error_type, APIErrorType.TIMEOUT)

    def test_classify_error_rate_limit(self):
        """レート制限エラーの分類"""
        client = LLMClient(api_key="test-key")

        # 実際のanthropicライブラリのRateLimitErrorをテスト
        from anthropic import RateLimitError
        import httpx
        # RateLimitErrorはhttpx.Responseを必要とするため、モックを作成
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.request = MagicMock()
        mock_response.status_code = 429  # Rate limit status code
        mock_response.headers = MagicMock()
        mock_response.headers.get = MagicMock(return_value=None)
        error = RateLimitError("Rate limit exceeded", response=mock_response, body=None)
        error_type = client._classify_error(error)
        self.assertEqual(error_type, APIErrorType.RATE_LIMIT)

    def test_classify_error_auth(self):
        """認証エラーの分類"""
        client = LLMClient(api_key="test-key")

        # 実際のanthropicライブラリのAuthenticationErrorをテスト
        from anthropic import AuthenticationError
        import httpx
        # AuthenticationErrorはhttpx.Responseを必要とするため、モックを作成
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.request = MagicMock()
        mock_response.status_code = 401  # Unauthorized status code
        mock_response.headers = MagicMock()
        mock_response.headers.get = MagicMock(return_value=None)
        error = AuthenticationError("Authentication failed", response=mock_response, body=None)
        error_type = client._classify_error(error)
        self.assertEqual(error_type, APIErrorType.AUTH_ERROR)

    def test_create_error_for_timeout(self):
        """タイムアウトエラーのMagiError作成"""
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(APIErrorType.TIMEOUT, Exception("タイムアウト"))

        self.assertEqual(error.code, ErrorCode.API_TIMEOUT.value)
        self.assertIn("タイムアウト", error.message)
        self.assertTrue(error.recoverable)

    def test_create_error_for_rate_limit(self):
        """レート制限エラーのMagiError作成"""
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(APIErrorType.RATE_LIMIT, Exception("レート制限"))

        self.assertEqual(error.code, ErrorCode.API_RATE_LIMIT.value)
        self.assertIn("レート制限", error.message)
        self.assertTrue(error.recoverable)

    def test_create_error_for_auth_error(self):
        """認証エラーのMagiError作成"""
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(APIErrorType.AUTH_ERROR, Exception("認証"))

        self.assertEqual(error.code, ErrorCode.API_AUTH_ERROR.value)
        self.assertIn("認証", error.message)
        self.assertFalse(error.recoverable)


class TestLLMClientAsync(unittest.TestCase):
    """LLMClientの非同期テスト"""

    def test_send_success(self):
        """正常なAPIリクエスト送信"""
        client = LLMClient(api_key="test-key")

        # モックレスポンスを作成
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="応答テキスト")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.model = "claude-sonnet-4-20250514"

        with patch.object(
            client._client.messages, "create",
            new_callable=AsyncMock,
            return_value=mock_response
        ):
            request = LLMRequest(
                system_prompt="システム",
                user_prompt="ユーザー"
            )

            async def run_test():
                response = await client.send(request)
                self.assertEqual(response.content, "応答テキスト")
                self.assertEqual(response.usage["input_tokens"], 100)
                self.assertEqual(response.model, "claude-sonnet-4-20250514")

            asyncio.run(run_test())

    def test_send_with_retry_on_timeout(self):
        """タイムアウト時のリトライ"""
        client = LLMClient(api_key="test-key", retry_count=3)

        # 最初の2回はタイムアウト、3回目で成功
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="成功")]
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 25
        mock_response.model = "claude-sonnet-4-20250514"

        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError()
            return mock_response

        with patch.object(
            client._client.messages, "create",
            side_effect=mock_create
        ):
            request = LLMRequest(
                system_prompt="システム",
                user_prompt="ユーザー"
            )

            async def run_test():
                response = await client.send(request)
                self.assertEqual(response.content, "成功")
                self.assertEqual(call_count, 3)

            asyncio.run(run_test())

    def test_send_with_retry_exhausted(self):
        """リトライ回数超過時のエラー"""
        client = LLMClient(api_key="test-key", retry_count=2)

        async def mock_create(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch.object(
            client._client.messages, "create",
            side_effect=mock_create
        ):
            request = LLMRequest(
                system_prompt="システム",
                user_prompt="ユーザー"
            )

            async def run_test():
                with self.assertRaises(MagiException) as context:
                    await client.send(request)
                # リトライ回数超過エラーを確認
                # MagiExceptionが正しくラップされていることを確認
                self.assertIsInstance(context.exception.error, MagiError)
                self.assertEqual(context.exception.error.code, ErrorCode.API_TIMEOUT.value)
                # 例外メッセージにタイムアウト関連メッセージが含まれることを確認
                self.assertIn("タイムアウト", str(context.exception))

            asyncio.run(run_test())

    def test_send_auth_error_no_retry(self):
        """認証エラー時はリトライしない"""
        client = LLMClient(api_key="test-key", retry_count=3)

        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 認証エラーをシミュレート
            from anthropic import AuthenticationError
            import httpx
            # AuthenticationErrorはhttpx.Responseを必要とするため、モックを作成
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.request = MagicMock()
            mock_response.status_code = 401  # Unauthorized status code
            mock_response.headers = MagicMock()
            mock_response.headers.get = MagicMock(return_value=None)
            raise AuthenticationError("Invalid API key", response=mock_response, body=None)

        with patch.object(
            client._client.messages, "create",
            side_effect=mock_create
        ):
            request = LLMRequest(
                system_prompt="システム",
                user_prompt="ユーザー"
            )

            async def run_test():
                with self.assertRaises(MagiException) as context:
                    await client.send(request)
                # 認証エラーはリトライしないので1回のみ
                self.assertEqual(call_count, 1)
                # MagiExceptionが正しくラップされていることを確認
                self.assertIsInstance(context.exception.error, MagiError)
                self.assertEqual(context.exception.error.code, ErrorCode.API_AUTH_ERROR.value)
                self.assertFalse(context.exception.error.recoverable)

            asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
