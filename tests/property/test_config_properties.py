"""
設定管理のプロパティテスト

**Feature: magi-core, Property 16: 設定読み込みと適用**
**Validates: Requirements 12.1, 12.3, 12.4**
"""

import os
import tempfile
import unittest
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from magi.config.manager import ConfigManager
from magi.config.settings import MagiSettings
from magi.errors import ErrorCode, MagiException

# 安全な文字列ストラテジー（null バイトやYAML特殊文字を除外）
safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),  # 文字と数字のみ
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=50,
).filter(lambda x: x.strip() and "\x00" not in x)


class TestConfigLoadingProperty(unittest.TestCase):
    """Property 16: 設定読み込みと適用のプロパティテスト"""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @given(
        api_key=safe_text,
        debate_rounds=st.integers(min_value=1, max_value=100),
        voting_threshold=st.sampled_from(["majority", "unanimous"]),
        output_format=st.sampled_from(["json", "markdown"]),
        timeout=st.integers(min_value=1, max_value=3600),
        retry_count=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    def test_env_values_are_correctly_applied(
        self,
        api_key: str,
        debate_rounds: int,
        voting_threshold: str,
        output_format: str,
        timeout: int,
        retry_count: int,
    ):
        """環境変数から読み込んだ値が正しく設定に適用される"""
        # 環境変数をクリアして設定
        for key in list(os.environ.keys()):
            if key.startswith("MAGI_"):
                del os.environ[key]

        os.environ["MAGI_API_KEY"] = api_key
        os.environ["MAGI_DEBATE_ROUNDS"] = str(debate_rounds)
        os.environ["MAGI_VOTING_THRESHOLD"] = voting_threshold
        os.environ["MAGI_OUTPUT_FORMAT"] = output_format
        os.environ["MAGI_TIMEOUT"] = str(timeout)
        os.environ["MAGI_RETRY_COUNT"] = str(retry_count)

        manager = ConfigManager()
        config = manager.load(force_reload=True)

        self.assertEqual(config.api_key, api_key)
        self.assertEqual(config.debate_rounds, debate_rounds)
        self.assertEqual(config.voting_threshold, voting_threshold)
        self.assertEqual(config.output_format, output_format)
        self.assertEqual(config.timeout, timeout)
        self.assertEqual(config.retry_count, retry_count)

    @given(
        api_key=safe_text,
        debate_rounds=st.integers(min_value=1, max_value=100),
        voting_threshold=st.sampled_from(["majority", "unanimous"]),
        output_format=st.sampled_from(["json", "markdown"]),
        timeout=st.integers(min_value=1, max_value=3600),
        retry_count=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    def test_file_values_are_correctly_applied(
        self,
        api_key: str,
        debate_rounds: int,
        voting_threshold: str,
        output_format: str,
        timeout: int,
        retry_count: int,
    ):
        """設定ファイルから読み込んだ値が正しく適用される"""
        for key in list(os.environ.keys()):
            if key.startswith("MAGI_"):
                del os.environ[key]

        yaml_content = f"""
api_key: "{api_key}"
debate_rounds: {debate_rounds}
voting_threshold: {voting_threshold}
output_format: {output_format}
timeout: {timeout}
retry_count: {retry_count}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            manager = ConfigManager()
            config = manager.load(config_path=config_path, force_reload=True)

            self.assertEqual(config.api_key, api_key)
            self.assertEqual(config.debate_rounds, debate_rounds)
            self.assertEqual(config.voting_threshold, voting_threshold)
            self.assertEqual(config.output_format, output_format)
            self.assertEqual(config.timeout, timeout)
            self.assertEqual(config.retry_count, retry_count)
        finally:
            config_path.unlink()

    @given(
        file_api_key=safe_text,
        env_api_key=safe_text,
        file_debate_rounds=st.integers(min_value=1, max_value=50),
        env_debate_rounds=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_env_overrides_file_values(
        self,
        file_api_key: str,
        env_api_key: str,
        file_debate_rounds: int,
        env_debate_rounds: int,
    ):
        """環境変数が設定ファイルの値を上書きする"""
        for key in list(os.environ.keys()):
            if key.startswith("MAGI_"):
                del os.environ[key]

        yaml_content = f"""
api_key: "{file_api_key}"
debate_rounds: {file_debate_rounds}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            os.environ["MAGI_API_KEY"] = env_api_key
            os.environ["MAGI_DEBATE_ROUNDS"] = str(env_debate_rounds)

            manager = ConfigManager()
            config = manager.load(config_path=config_path, force_reload=True)

            self.assertEqual(config.api_key, env_api_key)
            self.assertEqual(config.debate_rounds, env_debate_rounds)
        finally:
            config_path.unlink()


class TestConfigValidationProperty(unittest.TestCase):
    """設定バリデーションのプロパティテスト"""

    @given(
        api_key=safe_text,
        debate_rounds=st.integers(min_value=1, max_value=100),
        voting_threshold=st.sampled_from(["majority", "unanimous"]),
        output_format=st.sampled_from(["json", "markdown"]),
        timeout=st.integers(min_value=1, max_value=3600),
        retry_count=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    def test_valid_config_passes_validation(
        self,
        api_key: str,
        debate_rounds: int,
        voting_threshold: str,
        output_format: str,
        timeout: int,
        retry_count: int,
    ):
        """有効な設定値は常にバリデーションを通過する"""
        config = MagiSettings(
            api_key=api_key,
            debate_rounds=debate_rounds,
            voting_threshold=voting_threshold,
            output_format=output_format,
            timeout=timeout,
            retry_count=retry_count,
        )

        manager = ConfigManager()
        result = manager.validate(config)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    @given(
        api_key=safe_text,
        invalid_threshold=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ).filter(lambda x: x not in ["majority", "unanimous"]),
    )
    @settings(max_examples=50)
    def test_invalid_voting_threshold_fails_validation(
        self,
        api_key: str,
        invalid_threshold: str,
    ):
        """無効なvoting_thresholdは MagiException を送出する"""
        yaml_content = f'api_key: "{api_key}"\nvoting_threshold: {invalid_threshold}\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            manager = ConfigManager()
            with self.assertRaises(MagiException) as ctx:
                manager.load(config_path=config_path, force_reload=True)
        finally:
            config_path.unlink()

        self.assertIn(ErrorCode.CONFIG_INVALID_VALUE.value, str(ctx.exception))

    @given(
        api_key=safe_text,
        invalid_format=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ).filter(lambda x: x not in ["json", "markdown"]),
    )
    @settings(max_examples=50)
    def test_invalid_output_format_fails_validation(
        self,
        api_key: str,
        invalid_format: str,
    ):
        """無効なoutput_formatは MagiException を送出する"""
        yaml_content = f'api_key: "{api_key}"\noutput_format: {invalid_format}\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            manager = ConfigManager()
            with self.assertRaises(MagiException) as ctx:
                manager.load(config_path=config_path, force_reload=True)
        finally:
            config_path.unlink()

        self.assertIn(ErrorCode.CONFIG_INVALID_VALUE.value, str(ctx.exception))

    @given(
        api_key=safe_text,
        invalid_rounds=st.integers(max_value=0),
    )
    @settings(max_examples=50)
    def test_invalid_debate_rounds_fails_validation(
        self,
        api_key: str,
        invalid_rounds: int,
    ):
        """0以下のdebate_roundsは MagiException を送出する"""
        yaml_content = f'api_key: "{api_key}"\ndebate_rounds: {invalid_rounds}\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            manager = ConfigManager()
            with self.assertRaises(MagiException) as ctx:
                manager.load(config_path=config_path, force_reload=True)
        finally:
            config_path.unlink()

        self.assertIn(ErrorCode.CONFIG_INVALID_VALUE.value, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
