"""
PluginModel の Pydantic バリデーションテスト
"""

import unittest

from pydantic import ValidationError

from magi.plugins.loader import PluginModel


class TestPluginModelValidation(unittest.TestCase):
    """Pydantic モデルで構造/型/デフォルトを検証する"""

    def test_defaults_applied(self):
        """最低限の必須項目でデフォルトが補完される"""
        data = {
            "plugin": {
                "name": "sample",
                "hash": "sha256:" + "a" * 64,
            },
            "bridge": {
                "command": "echo ok",
                "interface": "stdio",
            },
        }

        model = PluginModel.model_validate(data)

        self.assertEqual(model.plugin.version, "1.0.0")
        self.assertEqual(model.plugin.description, "")
        self.assertEqual(model.bridge.timeout, 30)
        self.assertEqual(model.agent_overrides, {})

    def test_signature_or_hash_required(self):
        """署名またはハッシュが無い場合は ValidationError"""
        data = {
            "plugin": {
                "name": "sample",
            },
            "bridge": {
                "command": "echo ok",
                "interface": "stdio",
            },
        }

        with self.assertRaises(ValidationError):
            PluginModel.model_validate(data)

    def test_interface_must_be_valid_literal(self):
        """interface は 'stdio' または 'file' のみ許可"""
        data = {
            "plugin": {
                "name": "sample",
                "hash": "sha256:" + "b" * 64,
            },
            "bridge": {
                "command": "echo ok",
                "interface": "socket",
            },
        }

        with self.assertRaises(ValidationError):
            PluginModel.model_validate(data)

    def test_timeout_must_be_positive(self):
        """timeout は正の整数のみ"""
        data = {
            "plugin": {
                "name": "sample",
                "hash": "sha256:" + "c" * 64,
            },
            "bridge": {
                "command": "echo ok",
                "interface": "stdio",
                "timeout": 0,
            },
        }

        with self.assertRaises(ValidationError):
            PluginModel.model_validate(data)

    def test_agent_overrides_must_be_string_map(self):
        """agent_overrides は文字列→文字列マップのみ許可"""
        data = {
            "plugin": {
                "name": "sample",
                "hash": "sha256:" + "d" * 64,
            },
            "bridge": {
                "command": "echo ok",
                "interface": "stdio",
            },
            "agent_overrides": {"melchior": 123},
        }

        with self.assertRaises(ValidationError):
            PluginModel.model_validate(data)


if __name__ == "__main__":
    unittest.main()
