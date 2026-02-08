import unittest
from unittest.mock import MagicMock, patch
from magi.config.provider import ProviderConfigLoader, ProviderConfig, ProviderConfigs
from magi.errors import MagiException


class TestProviderConfigLoaderCache(unittest.TestCase):
    def setUp(self):
        self.loader = ProviderConfigLoader()

    def test_cache_validation_logic(self):
        """skip_validation=Trueでロードされたキャッシュが、
        その後のskip_validation=Falseの呼び出しで再利用されない(検証がスキップされない)ことを確認する
        """
        # モック設定: バリデーションに失敗するような不完全な設定を返す
        # api_keyが欠落しているなど
        invalid_providers = {
            "openai": ProviderConfig(
                provider_id="openai", model="gpt-4", api_key=""
            )  # api_key missing
        }

        with patch.object(
            self.loader, "_load_from_file", return_value=(invalid_providers, "openai")
        ):
            with patch.object(self.loader, "_load_from_env", return_value=({}, None)):
                # 1. skip_validation=True でロード -> 成功するはず
                config1 = self.loader.load(skip_validation=True)
                self.assertIsNotNone(config1)
                self.assertEqual(config1.default_provider, "openai")

                # キャッシュがセットされたことを確認
                self.assertIsNotNone(self.loader._cache)

                # 2. skip_validation=False (デフォルト) でロード -> バリデーションエラーになるはず
                # バグがある場合、未検証のキャッシュが返されてしまいエラーにならない
                with self.assertRaises(MagiException):
                    self.loader.load(skip_validation=False)

    def test_validated_cache_is_reused(self):
        """検証済みのキャッシュは再利用されることを確認"""
        valid_providers = {
            "openai": ProviderConfig(
                provider_id="openai", model="gpt-4", api_key="sk-test"
            )
        }

        with patch.object(
            self.loader, "_load_from_file", return_value=(valid_providers, "openai")
        ):
            with patch.object(self.loader, "_load_from_env", return_value=({}, None)):
                # 1. 最初のロード (検証あり)
                config1 = self.loader.load()

                # 2. 2回目のロード
                # _load_from_file が再度呼ばれないことを確認するために、Mockをリセットまたは確認
                with patch.object(self.loader, "_load_from_file") as mock_load_file:
                    config2 = self.loader.load()
                    self.assertIs(config1, config2)
                    mock_load_file.assert_not_called()
