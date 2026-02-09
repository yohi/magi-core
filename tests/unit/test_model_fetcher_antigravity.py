import unittest
from io import StringIO
from unittest.mock import patch
from magi.cli.model_fetcher import fetch_available_models
import sys


class TestModelFetcherAntigravity(unittest.TestCase):
    def test_fetch_antigravity_warning(self):
        """antigravityプロバイダー指定時に警告が出て空リストが返ることを確認"""
        with patch("sys.stderr", new=StringIO()) as fake_stderr:
            models = fetch_available_models("antigravity", "fake_token")
            
            self.assertEqual(models, [])
            
            stderr_output = fake_stderr.getvalue()
            self.assertIn("Warning: fetch_available_models should not be used for antigravity", stderr_output)
            self.assertIn("Use AntigravityAuthProvider.get_available_models instead", stderr_output)

if __name__ == "__main__":
    unittest.main()
