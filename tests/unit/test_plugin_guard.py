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

    def test_rejects_invalid_command_name(self):
        """コマンド名に禁止文字が含まれる場合は拒否する"""
        guard = PluginGuard()

        with self.assertRaises(MagiException):
            guard.validate("rm;rf", ["ok"])

    def test_none_arguments_are_skipped(self):
        """None 引数は無視されて正常に返る"""
        guard = PluginGuard()

        sanitized = guard.validate("echo", ["ok", None, "still_ok"])

        self.assertEqual(["ok", "still_ok"], sanitized)


if __name__ == "__main__":  # pragma: no cover - 実行用
    unittest.main()
