import unittest
from unittest.mock import MagicMock, patch
import sys
from io import StringIO

from magi.cli.main import MagiCLI
from magi.config.manager import Config


class TestMagiCLIAuthLogout(unittest.TestCase):
    def setUp(self):
        self.mock_config = MagicMock(spec=Config)
        self.cli = MagiCLI(config=self.mock_config)
        self.stderr = StringIO()
        self.original_stderr = sys.stderr
        sys.stderr = self.stderr

    def tearDown(self):
        sys.stderr = self.original_stderr

    @patch("magi.cli.main.TokenManager")
    def test_auth_logout_valid_provider(self, MockTokenManager):
        # Setup
        mock_token_manager = MockTokenManager.return_value
        provider_id = "antigravity"  # Valid auth-based provider

        # Execute
        result = self.cli._auth_logout(provider_id)

        # Verify
        self.assertEqual(result, 0)
        mock_token_manager.delete_token.assert_called_once_with(f"magi.{provider_id}")
        self.assertIn(f"Logged out from {provider_id}.", self.stderr.getvalue())

    @patch("magi.cli.main.TokenManager")
    def test_auth_logout_valid_provider_case_insensitive(self, MockTokenManager):
        # Setup
        mock_token_manager = MockTokenManager.return_value
        provider_id = "AntiGravity"  # Mixed case

        # Execute
        result = self.cli._auth_logout(provider_id)

        # Verify
        self.assertEqual(result, 0)
        mock_token_manager.delete_token.assert_called_once_with("magi.antigravity")
        self.assertIn("Logged out from antigravity.", self.stderr.getvalue())

    @patch("magi.cli.main.TokenManager")
    def test_auth_logout_invalid_provider(self, MockTokenManager):
        # Setup
        mock_token_manager = MockTokenManager.return_value
        provider_id = "openai"  # Not in AUTH_BASED_PROVIDERS (it's API key based)

        # Execute
        result = self.cli._auth_logout(provider_id)

        # Verify
        self.assertEqual(result, 1)
        mock_token_manager.delete_token.assert_not_called()
        self.assertIn(
            f"Error: '{provider_id}' is not a valid authentication provider.",
            self.stderr.getvalue(),
        )

    @patch("magi.cli.main.TokenManager")
    def test_auth_logout_exception(self, MockTokenManager):
        # Setup
        mock_token_manager = MockTokenManager.return_value
        mock_token_manager.delete_token.side_effect = Exception("Delete failed")
        provider_id = "antigravity"

        # Execute
        result = self.cli._auth_logout(provider_id)

        # Verify
        self.assertEqual(result, 1)
        mock_token_manager.delete_token.assert_called_once()
        self.assertIn("Logout failed: Delete failed", self.stderr.getvalue())

    def test_auth_logout_no_provider(self):
        # Execute
        result = self.cli._auth_logout(None)

        # Verify
        self.assertEqual(result, 1)
        self.assertIn(
            "Error: provider argument is required for logout.", self.stderr.getvalue()
        )
