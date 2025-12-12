"""
ProviderConfigLoader のユニットテスト
"""

import os
import tempfile
import unittest
from pathlib import Path

from magi.config.provider import (
    DEFAULT_PROVIDER_ID,
    ProviderConfigLoader,
)
from magi.errors import MagiException


class TestProviderConfigLoader(unittest.TestCase):
    """プロバイダ設定ローダーのテスト"""

    def setUp(self):
        self.original_env = os.environ.copy()
        self.loader = ProviderConfigLoader()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_loads_provider_from_env_only(self):
        """環境変数のみからプロバイダ設定を読み込める"""
        os.environ["MAGI_ANTHROPIC_API_KEY"] = "env-anthropic-key"
        os.environ["MAGI_ANTHROPIC_MODEL"] = "claude-3-haiku"
        os.environ["MAGI_ANTHROPIC_OPTIONS"] = '{"temperature":0.2}'

        configs = self.loader.load(force_reload=True)

        self.assertIn("anthropic", configs.providers)
        config = configs.providers["anthropic"]
        self.assertEqual(config.api_key, "env-anthropic-key")
        self.assertEqual(config.model, "claude-3-haiku")
        self.assertAlmostEqual(config.options.get("temperature"), 0.2)
        self.assertEqual(configs.default_provider, DEFAULT_PROVIDER_ID)
        self.assertNotEqual(config.masked_api_key, config.api_key)

    def test_env_overrides_file_and_config_default_wins_over_env_default(self):
        """ファイル設定に対して環境変数が上書きし、デフォルトは config が優先される"""
        yaml_content = """
providers:
  openai:
    api_key: file-openai-key
    model: gpt-4o
default_provider: openai
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            os.environ["MAGI_OPENAI_API_KEY"] = "env-openai-key"
            os.environ["MAGI_DEFAULT_PROVIDER"] = "gemini"

            configs = self.loader.load(config_path=config_path, force_reload=True)

            openai = configs.providers["openai"]
            self.assertEqual(openai.api_key, "env-openai-key")
            self.assertEqual(openai.model, "gpt-4o")
            # default_provider は config の値が優先される
            self.assertEqual(configs.default_provider, "openai")
        finally:
            config_path.unlink()

    def test_missing_required_fields_raises(self):
        """必須フィールド欠落時に明示的なエラーを返す"""
        yaml_content = """
providers:
  openai:
    model: gpt-4o
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            with self.assertRaises(MagiException) as ctx:
                self.loader.load(config_path=config_path, force_reload=True)

            error = ctx.exception.error
            self.assertIn("CONFIG", error.code)
            self.assertIn("openai", error.message)
            missing_fields = error.details.get("missing_fields", {})
            self.assertIn("openai", missing_fields)
            self.assertIn("api_key", missing_fields.get("openai", []))
        finally:
            config_path.unlink()

    def test_reload_reloads_provider_configs(self):
        """force_reload でキャッシュを無視して再読み込みできる"""
        os.environ["MAGI_ANTHROPIC_API_KEY"] = "first-key"
        os.environ["MAGI_ANTHROPIC_MODEL"] = "claude-3-haiku"

        first = self.loader.load(force_reload=True)
        self.assertEqual(first.providers["anthropic"].api_key, "first-key")

        os.environ["MAGI_ANTHROPIC_API_KEY"] = "second-key"
        second = self.loader.load(force_reload=True)

        self.assertNotEqual(first.providers["anthropic"].api_key, second.providers["anthropic"].api_key)
        self.assertEqual(second.providers["anthropic"].api_key, "second-key")


if __name__ == "__main__":
    unittest.main()
