"""LLMクライアントのユニットテスト

LLMクライアントの基本機能をテストする。
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch
from dataclasses import dataclass

from magi.llm.client import (
    LLMRequest,
    LLMResponse,
    LLMClient,
    APIErrorType,
)
from magi.errors import ErrorCode, MagiError, MagiException
from magi.models import Attachment


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

    def test_retry_with_full_jitter_for_rate_limit(self):
        """レート制限時にFull Jitterで待機し既定回数までリトライする"""
        client = LLMClient(
            api_key="test-key",
            retry_count=3,
            rate_limit_retry_count=4,
            base_delay_seconds=0.1,
            rate_limit_backoff_cap=1.0,
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="rate-ok")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.model = "model-x"

        call_count = 0

        async def mock_send(request):
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                from anthropic import RateLimitError
                import httpx

                mock_httpx_response = MagicMock(spec=httpx.Response)
                mock_httpx_response.request = MagicMock()
                mock_httpx_response.status_code = 429
                mock_httpx_response.headers = MagicMock()
                mock_httpx_response.headers.get = MagicMock(return_value=None)
                raise RateLimitError(
                    "Rate limit",
                    response=mock_httpx_response,
                    body=None,
                )
            return mock_response

        client._send_request = AsyncMock(side_effect=mock_send)

        jitter_values = [0.01, 0.02, 0.03]
        request = LLMRequest(system_prompt="s", user_prompt="u")
        with patch(
            "magi.llm.client.random.uniform",
            side_effect=jitter_values,
        ) as mock_uniform, patch(
            "magi.llm.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            asyncio.run(client.send(request))

        # 3回スリープして4回目で成功する
        self.assertEqual(mock_sleep.await_count, 3)
        self.assertEqual(call_count, 4)
        mock_uniform.assert_has_calls(
            [
                call(0, 0.1),
                call(0, 0.2),
                call(0, 0.4),
            ]
        )

    def test_rate_limit_records_metrics_and_logs_backoff(self):
        """レート制限時にメトリクス記録とバックオフログが出る"""
        from anthropic import RateLimitError
        import httpx

        # ConcurrencyControllerをモック化してレート制限記録を検証
        mock_controller = MagicMock()
        client = LLMClient(
            api_key="test-key",
            retry_count=2,
            base_delay_seconds=0.1,
            rate_limit_backoff_cap=0.2,
            min_rate_limit_backoff_seconds=0.05,
            concurrency_controller=mock_controller,
        )

        # 1回目は429を返し、2回目で成功する
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="rate-ok")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.model = "model-x"

        mock_httpx_response = MagicMock(spec=httpx.Response)
        mock_httpx_response.request = MagicMock()
        mock_httpx_response.status_code = 429
        mock_httpx_response.headers = MagicMock()
        mock_httpx_response.headers.get = MagicMock(return_value=None)

        rate_limit_error = RateLimitError(
            "Rate limit exceeded",
            response=mock_httpx_response,
            body=None,
        )

        call_count = 0

        async def mock_send(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_error
            return mock_response

        client._send_request = AsyncMock(side_effect=mock_send)
        request = LLMRequest(system_prompt="s", user_prompt="u")

        with patch(
            "magi.llm.client.random.uniform",
            return_value=0.0,
        ) as mock_uniform, patch(
            "magi.llm.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep, self.assertLogs(
            "magi.llm.client", level="WARNING"
        ) as log:
            asyncio.run(client.send(request))

        mock_controller.note_rate_limit.assert_called_once()
        self.assertEqual(mock_sleep.await_count, 1)
        sleep_arg = mock_sleep.await_args_list[0].args[0]
        self.assertGreaterEqual(sleep_arg, 0.05)
        mock_uniform.assert_called_once_with(0, 0.1)
        self.assertTrue(
            any("rate limit" in message.lower() for message in log.output)
        )

    def test_retry_with_full_jitter_for_timeout(self):
        """タイムアウト時にFull Jitterで3回試行し例外を送出する"""
        client = LLMClient(
            api_key="test-key",
            retry_count=3,
            base_delay_seconds=0.2,
            default_backoff_cap=1.0,
            default_retry_count=3,
        )
        client._send_request = AsyncMock(side_effect=asyncio.TimeoutError())

        request = LLMRequest(system_prompt="s", user_prompt="u")
        jitter_values = [0.05, 0.08]

        with patch(
            "magi.llm.client.random.uniform",
            side_effect=jitter_values,
        ) as mock_uniform, patch(
            "magi.llm.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            async def run_test():
                with self.assertRaises(MagiException):
                    await client.send(request)

            asyncio.run(run_test())

        # 3回試行し2回スリープしていることを確認
        self.assertEqual(client._send_request.await_count, 3)
        self.assertEqual(mock_sleep.await_count, 2)
        mock_uniform.assert_has_calls(
            [
                call(0, 0.2),
                call(0, 0.4),
            ]
        )


    def test_send_with_attachments(self):
        """添付ファイルを含むリクエストが正しく処理される"""
        client = LLMClient(api_key="test-key")

        # モックレスポンスを作成
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="画像を確認しました")]
        mock_response.usage.input_tokens = 150
        mock_response.usage.output_tokens = 30
        mock_response.model = "claude-sonnet-4-20250514"

        # テスト用の画像データ
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        attachment = Attachment(
            mime_type="image/png",
            data=image_data,
            filename="test.png"
        )

        with patch.object(
            client._client.messages, "create",
            new_callable=AsyncMock,
            return_value=mock_response
        ) as mock_create:
            request = LLMRequest(
                system_prompt="システム",
                user_prompt="この画像を説明してください",
                attachments=[attachment]
            )

            async def run_test():
                response = await client.send(request)
                self.assertEqual(response.content, "画像を確認しました")
                self.assertEqual(response.usage["input_tokens"], 150)
                
                # messages.createが正しい引数で呼ばれたことを確認
                call_args = mock_create.call_args
                messages = call_args.kwargs["messages"]
                self.assertEqual(len(messages), 1)
                
                # メッセージのcontentが配列形式であることを確認
                content = messages[0]["content"]
                self.assertIsInstance(content, list)
                self.assertEqual(len(content), 2)  # テキスト + 画像
                
                # テキストパートを確認
                text_part = content[0]
                self.assertEqual(text_part["type"], "text")
                self.assertEqual(text_part["text"], "この画像を説明してください")
                
                # 画像パートを確認
                image_part = content[1]
                self.assertEqual(image_part["type"], "image")
                self.assertEqual(image_part["source"]["type"], "base64")
                self.assertEqual(image_part["source"]["media_type"], "image/png")
                # base64エンコードされたデータが含まれていることを確認
                self.assertIn("data", image_part["source"])

            asyncio.run(run_test())



if __name__ == "__main__":
    unittest.main()
