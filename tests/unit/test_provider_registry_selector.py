"""
ProviderRegistry/Selector のユニットテスト
"""

import unittest

from magi.config.provider import ProviderConfig, ProviderConfigs
from magi.core.providers import ProviderRegistry, ProviderSelector
from magi.errors import MagiException


class TestProviderRegistry(unittest.TestCase):
    """ProviderRegistry の挙動を検証"""

    def test_resolve_registered_provider(self):
        """登録済みプロバイダを解決できる"""
        configs = ProviderConfigs(
            providers={
                "openai": ProviderConfig(
                    provider_id="openai",
                    api_key="openai-key",
                    model="gpt-4o",
                )
            },
            default_provider="openai",
        )

        registry = ProviderRegistry(configs)
        resolved = registry.resolve("openai")

        self.assertEqual(resolved.provider_id, "openai")
        self.assertEqual(resolved.model, "gpt-4o")

    def test_resolve_unknown_provider_fails_fast(self):
        """未登録プロバイダは fail-fast で例外"""
        configs = ProviderConfigs(providers={}, default_provider="anthropic")
        registry = ProviderRegistry(configs)

        with self.assertRaises(MagiException) as ctx:
            registry.resolve("gemini")

        self.assertIn("unknown provider", ctx.exception.error.message.lower())

    def test_missing_required_fields_is_reported(self):
        """必須フィールド欠落を検出してエラーを返す"""
        configs = ProviderConfigs(
            providers={
                "openai": ProviderConfig(
                    provider_id="openai",
                    api_key="",
                    model="",
                )
            },
            default_provider="openai",
        )
        registry = ProviderRegistry(configs)

        with self.assertRaises(MagiException) as ctx:
            registry.resolve("openai")

        details = ctx.exception.error.details or {}
        self.assertIn("api_key", details.get("missing_fields", []))
        self.assertIn("model", details.get("missing_fields", []))


class TestProviderSelector(unittest.TestCase):
    """ProviderSelector の挙動を検証"""

    def test_flag_overrides_default_provider(self):
        """フラグ指定がデフォルトより優先される"""
        configs = ProviderConfigs(
            providers={
                "anthropic": ProviderConfig(
                    provider_id="anthropic",
                    api_key="anthropic-key",
                    model="claude-3-haiku",
                ),
                "openai": ProviderConfig(
                    provider_id="openai",
                    api_key="openai-key",
                    model="gpt-4o",
                ),
            },
            default_provider="anthropic",
        )
        registry = ProviderRegistry(configs)
        selector = ProviderSelector(registry)

        ctx = selector.select("openai")

        self.assertEqual(ctx.provider_id, "openai")
        self.assertFalse(ctx.used_default)

    def test_default_provider_is_used_when_flag_absent(self):
        """フラグ未指定時はデフォルトプロバイダが選択される"""
        configs = ProviderConfigs(
            providers={
                "anthropic": ProviderConfig(
                    provider_id="anthropic",
                    api_key="anthropic-key",
                    model="claude-3-haiku",
                )
            },
            default_provider="anthropic",
        )
        registry = ProviderRegistry(configs)
        selector = ProviderSelector(registry)

        ctx = selector.select()

        self.assertEqual(ctx.provider_id, "anthropic")
        self.assertTrue(ctx.used_default)

    def test_selector_raises_if_provider_missing(self):
        """デフォルトプロバイダが登録されていなければエラー"""
        configs = ProviderConfigs(providers={}, default_provider="anthropic")
        registry = ProviderRegistry(configs)
        selector = ProviderSelector(registry)

        with self.assertRaises(MagiException) as ctx:
            selector.select()

        self.assertIn("provider", ctx.exception.error.message.lower())


if __name__ == "__main__":
    unittest.main()
