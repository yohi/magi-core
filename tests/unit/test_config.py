"""
ConfigManagerのユニットテスト
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from magi.config.manager import Config, ConfigManager, ValidationResult


class TestConfig(unittest.TestCase):
    """Configデータクラスのテスト"""

    def test_config_default_values(self):
        """デフォルト値が正しく設定されることを確認"""
        config = Config(api_key="test-api-key")

        self.assertEqual(config.api_key, "test-api-key")
        self.assertEqual(config.model, "claude-sonnet-4-20250514")
        self.assertEqual(config.debate_rounds, 1)
        self.assertEqual(config.voting_threshold, "majority")
        self.assertEqual(config.output_format, "markdown")
        self.assertEqual(config.timeout, 60)
        self.assertEqual(config.retry_count, 3)

    def test_config_custom_values(self):
        """カスタム値が正しく設定されることを確認"""
        config = Config(
            api_key="custom-api-key",
            model="claude-3-opus-20240229",
            debate_rounds=3,
            voting_threshold="unanimous",
            output_format="json",
            timeout=120,
            retry_count=5
        )

        self.assertEqual(config.api_key, "custom-api-key")
        self.assertEqual(config.model, "claude-3-opus-20240229")
        self.assertEqual(config.debate_rounds, 3)
        self.assertEqual(config.voting_threshold, "unanimous")
        self.assertEqual(config.output_format, "json")
        self.assertEqual(config.timeout, 120)
        self.assertEqual(config.retry_count, 5)


class TestValidationResult(unittest.TestCase):
    """ValidationResultデータクラスのテスト"""

    def test_valid_result(self):
        """有効な結果の作成"""
        result = ValidationResult(is_valid=True, errors=[])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_invalid_result_with_errors(self):
        """エラーを含む無効な結果の作成"""
        result = ValidationResult(is_valid=False, errors=["Error 1", "Error 2"])
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 2)


class TestConfigManagerLoadFromEnv(unittest.TestCase):
    """環境変数からの設定読み込みテスト"""

    def setUp(self):
        """テスト前にConfigManagerをリセット"""
        self.manager = ConfigManager()
        # 環境変数を保存
        self.original_env = os.environ.copy()

    def tearDown(self):
        """テスト後に環境変数を復元"""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_load_api_key_from_env(self):
        """MAGI_API_KEYから読み込み"""
        os.environ["MAGI_API_KEY"] = "env-api-key"

        config = self.manager.load()

        self.assertEqual(config.api_key, "env-api-key")

    def test_load_model_from_env(self):
        """MAGI_MODELから読み込み"""
        os.environ["MAGI_API_KEY"] = "test-key"
        os.environ["MAGI_MODEL"] = "claude-3-opus-20240229"

        config = self.manager.load()

        self.assertEqual(config.model, "claude-3-opus-20240229")

    def test_load_debate_rounds_from_env(self):
        """MAGI_DEBATE_ROUNDSから読み込み"""
        os.environ["MAGI_API_KEY"] = "test-key"
        os.environ["MAGI_DEBATE_ROUNDS"] = "5"

        config = self.manager.load()

        self.assertEqual(config.debate_rounds, 5)

    def test_load_voting_threshold_from_env(self):
        """MAGI_VOTING_THRESHOLDから読み込み"""
        os.environ["MAGI_API_KEY"] = "test-key"
        os.environ["MAGI_VOTING_THRESHOLD"] = "unanimous"

        config = self.manager.load()

        self.assertEqual(config.voting_threshold, "unanimous")

    def test_load_output_format_from_env(self):
        """MAGI_OUTPUT_FORMATから読み込み"""
        os.environ["MAGI_API_KEY"] = "test-key"
        os.environ["MAGI_OUTPUT_FORMAT"] = "json"

        config = self.manager.load()

        self.assertEqual(config.output_format, "json")

    def test_load_timeout_from_env(self):
        """MAGI_TIMEOUTから読み込み"""
        os.environ["MAGI_API_KEY"] = "test-key"
        os.environ["MAGI_TIMEOUT"] = "120"

        config = self.manager.load()

        self.assertEqual(config.timeout, 120)

    def test_load_retry_count_from_env(self):
        """MAGI_RETRY_COUNTから読み込み"""
        os.environ["MAGI_API_KEY"] = "test-key"
        os.environ["MAGI_RETRY_COUNT"] = "5"

        config = self.manager.load()

        self.assertEqual(config.retry_count, 5)

    def test_missing_api_key_raises_error(self):
        """APIキーが設定されていない場合はエラー"""
        # 環境変数をクリア
        for key in list(os.environ.keys()):
            if key.startswith("MAGI_"):
                del os.environ[key]

        from magi.errors import MagiException

        with self.assertRaises(MagiException) as context:
            self.manager.load()

        self.assertIn("CONFIG_001", str(context.exception))


class TestConfigManagerLoadFromFile(unittest.TestCase):
    """設定ファイルからの読み込みテスト"""

    def setUp(self):
        """テスト前にConfigManagerをリセット"""
        self.manager = ConfigManager()
        self.original_env = os.environ.copy()

    def tearDown(self):
        """テスト後に環境変数を復元"""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_load_from_yaml_file(self):
        """YAMLファイルからの読み込み"""
        yaml_content = """
api_key: file-api-key
model: claude-3-opus-20240229
debate_rounds: 3
voting_threshold: unanimous
output_format: json
timeout: 90
retry_count: 5
"""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            config = self.manager.load(config_path=config_path)

            self.assertEqual(config.api_key, "file-api-key")
            self.assertEqual(config.model, "claude-3-opus-20240229")
            self.assertEqual(config.debate_rounds, 3)
            self.assertEqual(config.voting_threshold, "unanimous")
            self.assertEqual(config.output_format, "json")
            self.assertEqual(config.timeout, 90)
            self.assertEqual(config.retry_count, 5)
        finally:
            config_path.unlink()

    def test_env_overrides_file(self):
        """環境変数がファイル設定を上書きする"""
        yaml_content = """
api_key: file-api-key
model: claude-sonnet-4-20250514
"""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            os.environ["MAGI_API_KEY"] = "env-api-key"
            os.environ["MAGI_MODEL"] = "claude-3-opus-20240229"

            config = self.manager.load(config_path=config_path)

            # 環境変数が優先される
            self.assertEqual(config.api_key, "env-api-key")
            self.assertEqual(config.model, "claude-3-opus-20240229")
        finally:
            config_path.unlink()

    def test_default_config_file_path(self):
        """デフォルトの設定ファイルパス（magi.yaml）からの読み込み"""
        yaml_content = """
api_key: default-file-api-key
"""
        # 一時ディレクトリに magi.yaml を作成
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "magi.yaml"
            config_path.write_text(yaml_content)

            with patch.object(
                ConfigManager, '_get_default_config_paths',
                return_value=[config_path]
            ):
                config = self.manager.load()

                self.assertEqual(config.api_key, "default-file-api-key")


class TestConfigManagerValidation(unittest.TestCase):
    """設定値のバリデーションテスト"""

    def setUp(self):
        """テスト前にConfigManagerをリセット"""
        self.manager = ConfigManager()
        self.original_env = os.environ.copy()

    def tearDown(self):
        """テスト後に環境変数を復元"""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_validate_valid_config(self):
        """有効な設定のバリデーション"""
        config = Config(
            api_key="test-key",
            voting_threshold="majority",
            output_format="markdown"
        )

        result = self.manager.validate(config)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_validate_invalid_voting_threshold(self):
        """無効なvoting_thresholdのバリデーション"""
        config = Config(
            api_key="test-key",
            voting_threshold="invalid"
        )

        result = self.manager.validate(config)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("voting_threshold" in e for e in result.errors))

    def test_validate_invalid_output_format(self):
        """無効なoutput_formatのバリデーション"""
        config = Config(
            api_key="test-key",
            output_format="invalid"
        )

        result = self.manager.validate(config)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("output_format" in e for e in result.errors))

    def test_validate_invalid_debate_rounds(self):
        """無効なdebate_roundsのバリデーション（0以下）"""
        config = Config(
            api_key="test-key",
            debate_rounds=0
        )

        result = self.manager.validate(config)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("debate_rounds" in e for e in result.errors))

    def test_validate_invalid_timeout(self):
        """無効なtimeoutのバリデーション（0以下）"""
        config = Config(
            api_key="test-key",
            timeout=0
        )

        result = self.manager.validate(config)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("timeout" in e for e in result.errors))

    def test_validate_invalid_retry_count(self):
        """無効なretry_countのバリデーション（負の値）"""
        config = Config(
            api_key="test-key",
            retry_count=-1
        )

        result = self.manager.validate(config)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("retry_count" in e for e in result.errors))

    def test_validate_empty_api_key(self):
        """空のAPIキーのバリデーション"""
        config = Config(api_key="")

        result = self.manager.validate(config)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("api_key" in e for e in result.errors))


class TestConfigManagerCaching(unittest.TestCase):
    """設定のキャッシュテスト"""

    def setUp(self):
        """テスト前にConfigManagerをリセット"""
        self.manager = ConfigManager()
        self.original_env = os.environ.copy()

    def tearDown(self):
        """テスト後に環境変数を復元"""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_config_is_cached(self):
        """設定がキャッシュされることを確認"""
        os.environ["MAGI_API_KEY"] = "test-key"

        config1 = self.manager.load()
        config2 = self.manager.load()

        self.assertIs(config1, config2)

    def test_force_reload(self):
        """強制リロードで新しい設定を取得"""
        os.environ["MAGI_API_KEY"] = "test-key-1"
        config1 = self.manager.load()

        os.environ["MAGI_API_KEY"] = "test-key-2"
        config2 = self.manager.load(force_reload=True)

        self.assertIsNot(config1, config2)
        self.assertEqual(config2.api_key, "test-key-2")


if __name__ == "__main__":
    unittest.main()
