"""PluginGuard のユニットテスト"""

import unittest

from magi.plugins.guard import PluginGuard
from magi.errors import MagiException


class TestPluginGuard(unittest.TestCase):
    """PluginGuard の検証テスト"""

    def test_rejects_meta_characters_in_args(self):
        """メタ文字を含む引数は拒否される"""
        guard = PluginGuard()

        with self.assertRaises(MagiException):
            guard.validate("echo", ["hello;rm -rf /"])

    def test_allows_whitelisted_command_and_args(self):
        """ホワイトリストに合致するコマンドと引数は許可される"""
        guard = PluginGuard()
        sanitized = guard.validate("echo", ["safe_input", "another"])

        self.assertEqual(sanitized, ["safe_input", "another"])


if __name__ == "__main__":  # pragma: no cover - 実行用
    unittest.main()
