import unittest
from unittest.mock import patch, MagicMock
from magi.cli.model_fetcher import fetch_available_models
import os


class TestModelFetcherAntigravity(unittest.TestCase):
    @patch("magi.cli.model_fetcher.httpx.post")
    def test_fetch_antigravity_success(self, mock_post):
        # モックの設定
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": {"gemini-pro": {}, "gemini-flash": {}, "claude-3-sonnet": {}}
        }
        mock_post.return_value = mock_response

        # テスト実行
        models = fetch_available_models("antigravity", "fake_token")

        # 検証
        self.assertEqual(models, ["claude-3-sonnet", "gemini-flash", "gemini-pro"])

        # 呼び出し引数の検証
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(
            args[0],
            "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake_token")
        self.assertEqual(kwargs["headers"]["User-Agent"], "antigravity")
        self.assertEqual(kwargs["json"], {})

    @patch("magi.cli.model_fetcher.httpx.post")
    def test_fetch_antigravity_with_env_endpoint(self, mock_post):
        """環境変数 ANTIGRAVITY_ENDPOINT が指定された場合の動作確認"""
        custom_endpoint = "https://custom.googleapis.com"
        # 環境変数をモック
        with patch.dict("os.environ", {"ANTIGRAVITY_ENDPOINT": custom_endpoint}):
            # モックの設定
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"models": {"custom-model": {}}}
            mock_post.return_value = mock_response

            # テスト実行
            models = fetch_available_models("antigravity", "fake_token")

            # 検証
            self.assertEqual(models, ["custom-model"])
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(
                args[0],
                f"{custom_endpoint}/v1internal:fetchAvailableModels",
            )

    @patch("magi.cli.model_fetcher.httpx.post")
    def test_fetch_antigravity_failure(self, mock_post):
        # モックの設定 (エラー)
        mock_post.side_effect = Exception("Connection error")

        # テスト実行
        models = fetch_available_models("antigravity", "fake_token")

        # 検証 (空リストが返るはず)
        self.assertEqual(models, [])

    @patch("magi.cli.model_fetcher.httpx.post")
    def test_fetch_antigravity_empty_response(self, mock_post):
        # モックの設定 (空レスポンス)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        # テスト実行
        models = fetch_available_models("antigravity", "fake_token")

        # 検証
        self.assertEqual(models, [])


if __name__ == "__main__":
    unittest.main()
