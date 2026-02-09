
import asyncio
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from magi.llm.auth.antigravity import AntigravityAuthProvider, AuthState, OAuthCallbackHandler
from magi.llm.auth.base import AuthContext


class TestOAuthCallbackHandler(unittest.TestCase):
    def setUp(self):
        self.server_mock = MagicMock()
        self.auth_state = AuthState()
        self.server_mock.auth_state = self.auth_state
        self.handler_mock = MagicMock()
        self.handler_mock.server = self.server_mock
        self.handler_mock.path = "/oauth-callback?code=test_code"
        self.handler_mock.command = "GET"
        
        self.handler_mock.send_response = MagicMock()
        self.handler_mock.send_header = MagicMock()
        self.handler_mock.end_headers = MagicMock()
        self.wfile_mock = MagicMock()
        self.handler_mock.wfile = self.wfile_mock

    def test_do_GET_success(self):
        with patch.object(OAuthCallbackHandler, '_send_response', wraps=self.handler_mock._send_response):
             OAuthCallbackHandler.do_GET(self.handler_mock)
             
             self.assertEqual(self.auth_state.code, "test_code")
             self.assertTrue(self.auth_state.completed.is_set())
             
             self.handler_mock._send_response.assert_called_with("Authentication successful!", code="test_code")

    def test_do_GET_error(self):
        self.handler_mock.path = "/oauth-callback?error=access_denied"
        
        OAuthCallbackHandler.do_GET(self.handler_mock)

        self.assertEqual(self.auth_state.error, "access_denied")
        self.assertTrue(self.auth_state.completed.is_set())
        
        self.handler_mock._send_response.assert_called_with("Authentication failed. You can close this window.", is_error=True)

    def test_send_response_html_content(self):
        handler = MagicMock()
        handler.wfile = MagicMock()
        
        OAuthCallbackHandler._send_response(handler, "Success", code="123")
        
        args, _ = handler.wfile.write.call_args
        html = args[0].decode("utf-8")
        self.assertIn("認証に成功しました", html)
        self.assertIn("123", html)
        
        OAuthCallbackHandler._send_response(handler, "Error", is_error=True)
        args, _ = handler.wfile.write.call_args
        html = args[0].decode("utf-8")
        self.assertIn("認証エラー", html)


class TestAntigravityAuthProvider(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = AuthContext(
            client_id="test_client_id",
            client_secret="test_client_secret"
        )
        self.token_manager = MagicMock()
        self.provider = AntigravityAuthProvider(self.context, self.token_manager, timeout_seconds=1.0)

    def test_extract_code_from_input_url_param(self):
        text = "http://localhost:51121/oauth-callback?code=4/test_code&scope=email"
        code = self.provider._extract_code_from_input(text)
        self.assertEqual(code, "4/test_code")

    def test_extract_code_from_input_google_format(self):
        text = "4/test_code_verifier_string"
        code = self.provider._extract_code_from_input(text)
        self.assertEqual(code, "4/test_code_verifier_string")

    def test_extract_code_from_input_raw_code(self):
        text = "some_very_long_random_string_that_looks_like_a_code"
        code = self.provider._extract_code_from_input(text)
        self.assertEqual(code, "some_very_long_random_string_that_looks_like_a_code")

    def test_extract_code_from_input_invalid(self):
        self.assertIsNone(self.provider._extract_code_from_input(""))
        self.assertIsNone(self.provider._extract_code_from_input("short"))
        self.assertIsNone(self.provider._extract_code_from_input("http://google.com"))

    @patch("webbrowser.open")
    @patch("magi.llm.auth.antigravity.HTTPServer")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._exchange_code_for_token")
    @patch("magi.llm.auth.antigravity.IPv4Server")
    @patch("magi.llm.auth.antigravity.DualStackServer")
    @patch("magi.llm.auth.antigravity.time.sleep")
    async def test_authenticate_hybrid_wait_server_wins(self, mock_sleep, mock_dual_stack, mock_ipv4, mock_exchange, mock_server_cls, mock_browser):
        mock_server = MagicMock()
        auth_state = AuthState()
        mock_server.auth_state = auth_state
        mock_dual_stack.return_value = mock_server
        mock_ipv4.return_value = mock_server

        mock_exchange.return_value = {
            "access_token": "new_access_token",
            "expires_in": 3600,
            "refresh_token": "new_refresh_token"
        }
        
        # input待機をブロックさせるための副作用関数
        stop_event = threading.Event()
        def blocking_input(*args):
            stop_event.wait(timeout=10)
            return "\n"
        
        mock_sleep.return_value = None

        with patch.object(AntigravityAuthProvider, "_readline", side_effect=blocking_input):
            task = asyncio.create_task(self.provider.authenticate())
            
            # サーバー側が先に完了する
            await asyncio.sleep(0.1)
            current_auth_state = mock_server.auth_state
            current_auth_state.code = "server_code"
            current_auth_state.completed.set()
            
            await task
            
            stop_event.set()

        mock_exchange.assert_called_once()
        args, _ = mock_exchange.call_args
        self.assertEqual(args[0], "server_code")
        
        self.token_manager.set_token.assert_called_once()
        stored_json = self.token_manager.set_token.call_args[0][1]
        stored_data = json.loads(stored_json)
        self.assertEqual(stored_data["access_token"], "new_access_token")

    @patch("webbrowser.open")
    @patch("magi.llm.auth.antigravity.HTTPServer")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._exchange_code_for_token")
    @patch("magi.llm.auth.antigravity.IPv4Server")
    @patch("magi.llm.auth.antigravity.DualStackServer")
    @patch("magi.llm.auth.antigravity.time.sleep")
    async def test_authenticate_hybrid_wait_input_wins(self, mock_sleep, mock_dual_stack, mock_ipv4, mock_exchange, mock_server_cls, mock_browser):
        mock_server = MagicMock()
        auth_state = AuthState()
        mock_server.auth_state = auth_state
        mock_dual_stack.return_value = mock_server
        mock_ipv4.return_value = mock_server
        
        mock_exchange.return_value = {
            "access_token": "manual_access_token",
            "expires_in": 3600
        }
        
        mock_sleep.return_value = None
        with patch.object(AntigravityAuthProvider, "_readline", side_effect=["manual_code_input\n"]):
             await self.provider.authenticate()

        mock_exchange.assert_called_once()
        args, _ = mock_exchange.call_args
        self.assertEqual(args[0], "manual_code_input")
        
        stored_json = self.token_manager.set_token.call_args[0][1]
        stored_data = json.loads(stored_json)
        self.assertEqual(stored_data["access_token"], "manual_access_token")

if __name__ == "__main__":
    unittest.main()
