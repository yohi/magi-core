import unittest
from magi.core.utils import normalize_model_name

class TestUtils(unittest.TestCase):
    def test_normalize_model_name_strips_prefixes(self):
        """モデル名のプレフィックス剥離が正しく行われることを確認"""
        # (input_model, target_provider) -> (expected_provider, expected_model)
        test_cases = [
            ("anthropic/claude-3", None, "anthropic", "claude-3"),
            ("openai/gpt-4o", None, "openai", "gpt-4o"),
            ("google/gemini-pro", None, "gemini", "gemini-pro"),
            ("gemini/gemini-pro", None, "gemini", "gemini-pro"),
            ("openrouter/anthropic/claude-3", None, "openrouter", "anthropic/claude-3"),
            ("openrouter/google/gemini", None, "openrouter", "google/gemini"),
            ("claude-3", "anthropic", "anthropic", "claude-3"),
            ("anthropic/claude-3", "openrouter", "openrouter", "anthropic/claude-3"),
            ("", "openai", "openai", ""),
            (None, "openai", "openai", None),
        ]

        for model, target, exp_provider, exp_model in test_cases:
            with self.subTest(model=model, target=target):
                p, m = normalize_model_name(model, target)
                self.assertEqual(p, exp_provider)
                self.assertEqual(m, exp_model)

if __name__ == "__main__":
    unittest.main()
