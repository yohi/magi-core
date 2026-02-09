import asyncio
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from magi.llm.auth import AuthContext
from magi.llm.auth.antigravity import AntigravityAuthProvider, AuthState


class TestAntigravityAuth(unittest.TestCase):
    def setUp(self):
        self.context = AuthContext(
            client_id="test_id",
            client_secret="test_secret",
            token_url="http://test/token",
            auth_url="http://test/auth",
            scopes=["scope"],
        )
        self.provider = AntigravityAuthProvider(self.context, timeout_seconds=2.0)

    @patch("magi.llm.auth.antigravity.webbrowser.open")
    @patch("magi.llm.auth.antigravity.HTTPServer")
    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    @patch("magi.llm.auth.antigravity.asyncio.to_thread")
    def test_authenticate_wait_for_completion(self, mock_to_thread, mock_client, mock_server_cls, mock_browser):
        """authenticateメソッドがcompletedイベントを待機することを確認"""
        
        # input()のモック (Enterのみ押された場合)
        mock_to_thread.return_value = ""
        
        # モックの設定
        mock_server_instance = MagicMock()
        mock_server_cls.return_value = mock_server_instance
        # server_addressはタプルを返す必要がある
        mock_server_instance.server_address = ("localhost", 12345)
        
        # httpxのモックレスポンス
        mock_response = MagicMock()
        mock_response.is_error = False
        mock_response.json.return_value = {
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_in": 3600,
            "token_type": "Bearer"
        }
        
        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_client_instance

        # 認証フローを別スレッドでシミュレート
        async def run_auth():
            await self.provider.authenticate()

        # イベントループで実行
        loop = asyncio.new_event_loop()
        auth_task = loop.create_task(run_auth())

        # 1. authenticate開始後、少し待ってからcodeをセット
        def simulate_browser_callback():
            time.sleep(0.5)
            # authenticate内でserver.auth_stateにセットされたインスタンスを取得
            current_auth_state = mock_server_instance.auth_state
            
            # codeをセット
            current_auth_state.code = "test_code"
            # completedをセット (whileループを抜けさせる)
            current_auth_state.completed.set()

        threading.Thread(target=simulate_browser_callback).start()

        # 実行
        loop.run_until_complete(auth_task)
        loop.close()

        # 検証
        current_auth_state = mock_server_instance.auth_state
        self.assertTrue(current_auth_state.completed.is_set())
        mock_server_instance.shutdown.assert_called_once()
        mock_server_instance.server_close.assert_called_once()
        
    @patch("magi.llm.auth.antigravity.webbrowser.open")
    @patch("magi.llm.auth.antigravity.HTTPServer")
    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    @patch("magi.llm.auth.antigravity.asyncio.to_thread")
    def test_authenticate_timeout(self, mock_to_thread, mock_client, mock_server_cls, mock_browser):
        """authenticateメソッドがタイムアウトすることを確認"""
        
        # input()のモック (Enterのみ押された場合)
        mock_to_thread.return_value = ""
        
        mock_server_instance = MagicMock()
        mock_server_cls.return_value = mock_server_instance
        mock_server_instance.server_address = ("localhost", 12345)
        
        auth_state = AuthState()
        mock_server_instance.auth_state = auth_state

        async def run_auth():
            # 短いタイムアウトで実行
            provider = AntigravityAuthProvider(self.context, timeout_seconds=0.5)
            await provider.authenticate()

        loop = asyncio.new_event_loop()
        with self.assertRaises(RuntimeError) as cm:
            loop.run_until_complete(run_auth())
        
        self.assertIn("timed out", str(cm.exception))
        loop.close()

    @patch("magi.llm.auth.antigravity.webbrowser.open")
    @patch("magi.llm.auth.antigravity.HTTPServer")
    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    @patch("magi.llm.auth.antigravity.asyncio.to_thread")
    def test_authenticate_regex_extraction(self, mock_to_thread, mock_client, mock_server_cls, mock_browser):
        """正規表現による認証コード抽出を確認"""
        
        # ユーザーが「余計なテキスト」と一緒に「4/」形式のコードを入力した場合をシミュレート
        mock_to_thread.return_value = "既存のブラウザセッション... 認証コード: 4/test_abc_123_XYZ"
        
        mock_server_instance = MagicMock()
        mock_server_cls.return_value = mock_server_instance
        mock_server_instance.server_address = ("localhost", 12345)
        
        # httpxのモックレスポンス
        mock_response = MagicMock()
        mock_response.is_error = False
        mock_response.json.return_value = {
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_in": 3600,
            "token_type": "Bearer"
        }
        
        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_client_instance

        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.provider.authenticate())
        loop.close()

        # 交換に使用されたコードが抽出されたものであることを確認
        mock_client_instance.post.assert_called_once()
        call_args = mock_client_instance.post.call_args
        self.assertEqual(call_args[1]["data"]["code"], "4/test_abc_123_XYZ")

if __name__ == "__main__":
    unittest.main()
