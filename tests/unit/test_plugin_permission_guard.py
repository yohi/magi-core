"""PluginPermissionGuard のユニットテスト"""

import unittest

from magi.config.settings import MagiSettings
from magi.plugins.loader import BridgeConfig, Plugin, PluginMetadata
from magi.plugins.permission_guard import OverrideScope, PluginPermissionGuard


class TestPluginPermissionGuard(unittest.TestCase):
    """プラグインのプロンプト権限チェックを検証する"""

    def _make_plugin(self, name: str = "sample") -> Plugin:
        """テスト用の簡易プラグインを生成する"""
        return Plugin(
            metadata=PluginMetadata(name=name),
            bridge=BridgeConfig(command="echo", interface="stdio", timeout=30),
        )

    def test_denies_full_override_when_not_allowed(self):
        """設定でフルオーバーライドが無効な場合は拒否する"""
        settings = MagiSettings(api_key="dummy-key")
        guard = PluginPermissionGuard(settings=settings)
        plugin = self._make_plugin("blocked-plugin")
        overrides = {"melchior": "override prompt"}

        with self.assertLogs("magi.plugins.permission_guard", level="WARNING") as logs:
            result = guard.check_override_permission(plugin, overrides)

        self.assertFalse(result.allowed)
        self.assertEqual(result.scope, OverrideScope.CONTEXT_ONLY)
        self.assertEqual(result.filtered_overrides, {})
        self.assertIn("blocked-plugin", "\n".join(logs.output))
        self.assertIn("full override is disabled", "\n".join(logs.output))

    def test_allows_full_override_when_enabled(self):
        """設定で許可されている場合はフルオーバーライドを許可する"""
        settings = MagiSettings(
            api_key="dummy-key",
            plugin_prompt_override_allowed=True,
        )
        guard = PluginPermissionGuard(settings=settings)
        plugin = self._make_plugin("permitted-plugin")
        overrides = {"balthasar": "override prompt"}

        result = guard.check_override_permission(plugin, overrides)

        self.assertTrue(result.allowed)
        self.assertEqual(result.scope, OverrideScope.FULL_OVERRIDE)
        self.assertEqual(result.filtered_overrides, overrides)
        self.assertIsNone(result.reason)

    def test_allows_noop_when_overrides_empty(self):
        """オーバーライドが無い場合はそのまま許可する"""
        settings = MagiSettings(api_key="dummy-key")
        guard = PluginPermissionGuard(settings=settings)
        plugin = self._make_plugin("noop-plugin")

        result = guard.check_override_permission(plugin, {})

        self.assertTrue(result.allowed)
        self.assertEqual(result.scope, OverrideScope.CONTEXT_ONLY)
        self.assertEqual(result.filtered_overrides, {})
        self.assertIsNone(result.reason)


if __name__ == "__main__":  # pragma: no cover - 実行用
    unittest.main()
