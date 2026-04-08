"""
モデル名の正規化に関するユニットテスト

model_name からプロバイダプレフィックスを剥離し、プロバイダIDを推測する
normalize_model_name 関数の動作を検証します。
"""
import unittest
from magi.core.utils import normalize_model_name

class TestModelNormalization(unittest.TestCase):
    """normalize_model_name の挙動を検証するクラス"""

    def test_strip_native_provider_prefixes(self) -> None:
        """ネイティブプロバイダのプレフィックスが正しく剥離されることを確認"""
        test_cases = [
            ("anthropic/claude-3-5-sonnet", "anthropic", "claude-3-5-sonnet"),
            ("openai/gpt-4o", "openai", "gpt-4o"),
            ("google/gemini-1.5-pro", "gemini", "gemini-1.5-pro"),
            ("gemini/gemini-2.0-flash", "gemini", "gemini-2.0-flash"),
        ]
        for full_name, expected_provider, expected_model in test_cases:
            with self.subTest(full_name=full_name):
                provider, model = normalize_model_name(full_name)
                self.assertEqual(provider, expected_provider)
                self.assertEqual(model, expected_model)

    def test_strip_openrouter_prefix_only(self) -> None:
        """openrouter/ プレフィックスのみが剥離され、二次プロバイダは維持されることを確認"""
        test_cases = [
            ("openrouter/google/gemini-pro", "openrouter", "google/gemini-pro"),
            ("openrouter/anthropic/claude-3", "openrouter", "anthropic/claude-3"),
            ("openrouter/openai/gpt-4", "openrouter", "openai/gpt-4"),
        ]
        for full_name, expected_provider, expected_model in test_cases:
            with self.subTest(full_name=full_name):
                provider, model = normalize_model_name(full_name)
                self.assertEqual(provider, expected_provider)
                self.assertEqual(model, expected_model)

    def test_no_strip_when_target_is_openrouter(self) -> None:
        """既にターゲットが openrouter と判明している場合は剥離されないことを確認"""
        provider, model = normalize_model_name("google/gemini", target_provider="openrouter")
        self.assertEqual(provider, "openrouter")
        self.assertEqual(model, "google/gemini")

    def test_unrecognized_prefix_preserves_name(self) -> None:
        """未知のプレフィックスの場合は、model_name が維持されることを確認"""
        provider, model = normalize_model_name("unknown/model-x", target_provider="default")
        self.assertEqual(provider, "default")
        self.assertEqual(model, "unknown/model-x")

if __name__ == "__main__":
    unittest.main()
