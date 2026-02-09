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
        self.provider = AntigravityAuthProvider(self.context, timeout_seconds=5.0)

    @patch("magi.llm.auth.antigravity.webbrowser.open")
    @patch("magi.llm.auth.antigravity.DualStackServer")
    @patch("magi.llm.auth.antigravity.IPv4Server")
    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._readline")
    @patch("magi.llm.auth.antigravity.time.sleep")
    def test_authenticate_wait_for_completion(self, mock_sleep, mock_readline, mock_client, mock_ipv4, mock_dual_stack, mock_browser):
        """authenticateメソッドがcompletedイベントを待機することを確認"""
        
        # input()のモック (サーバー側が勝つまでブロックさせる)
        stop_event = threading.Event()
        mock_readline.side_effect = lambda *args: stop_event.wait(timeout=10) or "\n"
        mock_sleep.return_value = None
        
        # モックの設定
        mock_server_instance = MagicMock()
        mock_dual_stack.return_value = mock_server_instance
        mock_ipv4.return_value = mock_server_instance
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
            # mock_sleepがpatchされているので、time.sleepは即座に返る
            # threading.Event().waitで実時間を待機
            threading.Event().wait(0.5)
            current_auth_state = mock_server_instance.auth_state
            
            # AuthStateがセットされるまで待つ（MagicMockであれば待つ）
            # ただし無限ループ防止のため回数制限
            for _ in range(10):
                if not isinstance(current_auth_state, MagicMock):
                    break
                threading.Event().wait(0.1)
                current_auth_state = mock_server_instance.auth_state

            if not isinstance(current_auth_state, MagicMock):
                current_auth_state.code = "test_code"
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
    @patch("magi.llm.auth.antigravity.DualStackServer")
    @patch("magi.llm.auth.antigravity.IPv4Server")
    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._readline")
    @patch("magi.llm.auth.antigravity.time.sleep")
    def test_authenticate_timeout(self, mock_sleep, mock_readline, mock_client, mock_ipv4, mock_dual_stack, mock_browser):
        """authenticateメソッドがタイムアウトすることを確認"""
        
        # input()のモック (ブロックさせる)
        mock_readline.side_effect = lambda *args: threading.Event().wait(timeout=10) or "\n"
        mock_sleep.return_value = None
        
        mock_server_instance = MagicMock()
        mock_dual_stack.return_value = mock_server_instance
        mock_ipv4.return_value = mock_server_instance
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
    @patch("magi.llm.auth.antigravity.DualStackServer")
    @patch("magi.llm.auth.antigravity.IPv4Server")
    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._readline")
    @patch("magi.llm.auth.antigravity.time.sleep")
    def test_authenticate_regex_extraction(self, mock_sleep, mock_readline, mock_client, mock_ipv4, mock_dual_stack, mock_browser):
        """正規表現による認証コード抽出を確認"""
        
        # ユーザーが「余計なテキスト」と一緒に「4/」形式のコードを入力した場合をシミュレート
        mock_readline.return_value = "既存のブラウザセッション... 認証コード: 4/test_abc_123_XYZ\n"
        mock_sleep.return_value = None
        
        mock_server_instance = MagicMock()
        mock_dual_stack.return_value = mock_server_instance
        mock_ipv4.return_value = mock_server_instance
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

    @patch("magi.llm.auth.antigravity.httpx.AsyncClient")
    def test_fetch_with_fallback_conditions(self, mock_client):
        """_fetch_with_fallbackが400, 404, 5xxでフォールバックすることを確認"""
        mock_client_instance = AsyncMock()
        mock_client.return_value = mock_client_instance
        mock_client_instance.__aenter__.return_value = mock_client_instance

        # 400, 404, 200 の順にレスポンスを返すように設定
        res400 = MagicMock()
        res400.status_code = 400
        res404 = MagicMock()
        res404.status_code = 404
        res200 = MagicMock()
        res200.status_code = 200

        mock_client_instance.post.side_effect = [res400, res404, res200]

        async def run_fetch():
            return await self.provider._fetch_with_fallback("/test", {}, {})

        loop = asyncio.new_event_loop()
        response = loop.run_until_complete(run_fetch())
        loop.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_client_instance.post.call_count, 3)

if __name__ == "__main__":
    unittest.main()
