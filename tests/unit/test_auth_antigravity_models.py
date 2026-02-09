import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from magi.llm.auth import AuthContext
from magi.llm.auth.antigravity import AntigravityAuthProvider

class TestAntigravityModels(unittest.TestCase):
    def setUp(self):
        self.context = AuthContext(
            client_id="test_id",
            client_secret="test_secret",
            token_url="http://test/token",
            auth_url="http://test/auth",
            scopes=["scope"],
        )
        self.provider = AntigravityAuthProvider(self.context, timeout_seconds=5.0)

    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_token")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_project_id")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._fetch_with_fallback")
    def test_get_available_models_success(self, mock_fetch, mock_get_project_id, mock_get_token):
        mock_get_token.return_value = "fake_token"
        mock_get_project_id.return_value = "test-project"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": {"gemini-pro": {}, "gemini-flash": {}, "claude-3-sonnet": {}}
        }
        mock_fetch.return_value = mock_response

        loop = asyncio.new_event_loop()
        models = loop.run_until_complete(self.provider.get_available_models())
        loop.close()

        self.assertEqual(models, ["claude-3-sonnet", "gemini-flash", "gemini-pro"])
        
        mock_fetch.assert_called_once()
        args, _ = mock_fetch.call_args
        self.assertEqual(args[0], "/v1internal:fetchAvailableModels")
        self.assertEqual(args[1]["Authorization"], "Bearer fake_token")
        self.assertEqual(args[2], {"project": "test-project"})

    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_token")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_project_id")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._fetch_with_fallback")
    def test_get_available_models_list_format(self, mock_fetch, mock_get_project_id, mock_get_token):
        mock_get_token.return_value = "fake_token"
        mock_get_project_id.return_value = "test-project"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "model-a"},
                "model-b"
            ]
        }
        mock_fetch.return_value = mock_response

        loop = asyncio.new_event_loop()
        models = loop.run_until_complete(self.provider.get_available_models())
        loop.close()

        self.assertEqual(models, ["model-a", "model-b"])

    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_token")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_project_id")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._fetch_with_fallback")
    def test_get_available_models_failure(self, mock_fetch, mock_get_project_id, mock_get_token):
        mock_get_token.return_value = "fake_token"
        mock_get_project_id.return_value = "test-project"
        
        mock_fetch.side_effect = Exception("Connection error")

        loop = asyncio.new_event_loop()
        models = loop.run_until_complete(self.provider.get_available_models())
        loop.close()

        self.assertEqual(models, [])

    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_token")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider.get_project_id")
    @patch("magi.llm.auth.antigravity.AntigravityAuthProvider._fetch_with_fallback")
    def test_get_available_models_reauth(self, mock_fetch, mock_get_project_id, mock_get_token):
        mock_get_token.side_effect = ["old_token", "new_token"]
        mock_get_project_id.return_value = "test-project"
        
        res401 = MagicMock()
        res401.status_code = 401
        
        res200 = MagicMock()
        res200.status_code = 200
        res200.json.return_value = {"models": {"new-model": {}}}
        
        mock_fetch.side_effect = [res401, res200]

        loop = asyncio.new_event_loop()
        models = loop.run_until_complete(self.provider.get_available_models())
        loop.close()

        self.assertEqual(models, ["new-model"])
        self.assertEqual(mock_get_token.call_count, 2)
        mock_get_token.assert_called_with(force_refresh=True)

if __name__ == "__main__":
    unittest.main()
