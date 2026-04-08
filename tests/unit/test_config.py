"""
ConfigManager のユニットテスト（MagiSettings 統合）
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from magi.config.manager import ConfigManager
from magi.config.settings import MagiSettings
from magi.errors import ErrorCode, MagiException
from magi.cli.parser import ArgumentParser


class TestConfigManagerWithMagiSettings(unittest.TestCase):
    """ConfigManager が MagiSettings を返すことを検証する"""

    def setUp(self):
        self.original_env = os.environ.copy()
        # テストの隔離性を確保するため、MAGI_ で始まる環境変数を一旦クリアする
        for key in list(os.environ.keys()):
            if key.startswith("MAGI_"):
                del os.environ[key]
        # ローカルの magi.yaml などを読み込まないようにデフォルトパスを空にする
        self.patcher = patch.object(ConfigManager, "_get_default_config_paths", return_value=[])
        self.patcher.start()
        # 最後にマネージャを初期化し、クリーンな環境とパッチ後の状態を認識させる
        self.manager = ConfigManager()

    def tearDown(self):
        self.patcher.stop()
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_load_returns_magi_settings_and_defaults(self):
        """最低限の必須項目のみで MagiSettings が返る"""
        os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "env-api-key"

        config = self.manager.load()

        self.assertIsInstance(config, MagiSettings)
        self.assertEqual(config.providers["anthropic"]["api_key"], "env-api-key")
        self.assertEqual(config.model, "claude-3-5-sonnet-20241022")
        self.assertEqual(config.llm_concurrency_limit, 5)
        self.assertTrue(config.log_context_reduction_key)

    def test_env_overrides_file_settings(self):
        """環境変数がファイル設定より優先される"""
        yaml_content = "providers:\n  anthropic:\n    api_key: file-key\nmodel: file-model\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "env-key"
            os.environ["MAGI_MODEL"] = "env-model"

            config = self.manager.load(config_path=config_path)

            self.assertEqual(config.providers["anthropic"]["api_key"], "env-key")
            self.assertEqual(config.model, "env-model")
        finally:
            config_path.unlink()

    def test_missing_api_key_is_allowed(self):
        """API キー欠如でもロード可能"""
        for key in list(os.environ.keys()):
            if key.startswith("MAGI_"):
                del os.environ[key]

        config = self.manager.load()
        # providers 自体は default_factory=dict により空辞書になるはず
        self.assertNotIn("anthropic", config.providers)

    def test_invalid_value_raises_magi_exception(self):
        """無効な値は MagiException(CONFIG_002) を送出"""
        os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "env-api-key"
        yaml_content = "voting_threshold: invalid\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            with self.assertRaises(MagiException) as ctx:
                self.manager.load(config_path=config_path)
        finally:
            config_path.unlink()

        self.assertIn(ErrorCode.CONFIG_INVALID_VALUE.value, str(ctx.exception))

    def test_unknown_fields_are_rejected(self):
        """未知フィールドはバリデーションエラーとなる"""
        os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "env-api-key"
        yaml_content = "unknown_field: value\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            with self.assertRaises(MagiException):
                self.manager.load(config_path=config_path)
        finally:
            config_path.unlink()

    def test_default_config_file_path(self):
        """デフォルトパス探索で magi.yaml が読み込まれる"""
        yaml_content = "providers:\n  anthropic:\n    api_key: default-file-api-key\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "magi.yaml"
            config_path.write_text(yaml_content)

            with patch.object(
                ConfigManager, "_get_default_config_paths", return_value=[config_path]
            ):
                config = self.manager.load()

                self.assertEqual(config.providers["anthropic"]["api_key"], "default-file-api-key")

    def test_config_cache_and_force_reload(self):
        """キャッシュと強制リロードが機能する"""
        os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "first"
        first = self.manager.load()

        os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "second"
        cached = self.manager.load()
        reloaded = self.manager.load(force_reload=True)

        self.assertIs(first, cached)
        self.assertIsNot(first, reloaded)
        self.assertEqual(reloaded.providers["anthropic"]["api_key"], "second")

    def test_dump_masked_provides_masked_values(self):
        """マスク済み設定を取得できる"""
        os.environ["MAGI_PROVIDERS__anthropic__api_key"] = "1234567890abcdef"
        config = self.manager.load()

        masked = self.manager.dump_masked()

        self.assertNotIn("api_key", masked)
        self.assertEqual(masked["providers"]["anthropic"]["api_key"], "12345678...cdef")
        self.assertEqual(masked["model"], config.model)


class TestConfigCheckOption(unittest.TestCase):
    """--config-check オプションの解析を検証する"""

    def test_config_check_without_command_is_valid(self):
        parser = ArgumentParser()
        parsed = parser.parse(["--config-check"])

        self.assertTrue(parsed.options.get("config_check"))
        validation = parser.validate(parsed)
        self.assertTrue(validation.is_valid)
