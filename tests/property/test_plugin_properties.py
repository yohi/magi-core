"""
プラグインシステムのプロパティテスト

Property 13: YAMLパースとメタデータ抽出
Property 14: 無効なYAMLのエラーハンドリング
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
import sys

from hypothesis import given, settings, assume, example
from hypothesis.strategies import (
    text, dictionaries, sampled_from, integers, 
    none, one_of, just, lists, fixed_dictionaries
)

from magi.plugins.loader import (
    PluginLoader, PluginMetadata, BridgeConfig, 
    Plugin, ValidationResult
)
from magi.errors import MagiException, ErrorCode
from magi.models import PersonaType


# 有効なプラグイン名のストラテジー（空やNULL文字を除く）
valid_plugin_name = text(
    min_size=1, 
    max_size=50,
    alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'
).filter(lambda s: s.strip() != '')

# 有効なバージョン文字列のストラテジー
valid_version = text(
    min_size=1,
    max_size=20,
    alphabet='0123456789.'
).filter(lambda s: s != '' and s[0] != '.' and s[-1] != '.')

# 有効なコマンド文字列のストラテジー
valid_command = text(
    min_size=1,
    max_size=100,
    alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./ '
).filter(lambda s: s.strip() != '')

# オーバーライドプロンプトのストラテジー（任意の文字列、YAML安全）
override_prompt = text(
    min_size=0,
    max_size=200,
    alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-. \n'
)


class TestPluginLoaderProperty13(unittest.TestCase):
    """
    **Feature: magi-core, Property 13: YAMLパースとメタデータ抽出**
    
    *For any* 有効なプラグインYAML定義に対して、パースが成功しメタデータが正しく抽出される
    
    **Validates: Requirements 8.1, 8.2**
    """

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.temp_path = Path(self.tmpdir.name)
        self.loader = PluginLoader()

    def tearDown(self):
        self.tmpdir.cleanup()

    @given(
        plugin_name=valid_plugin_name,
        plugin_version=valid_version,
        plugin_description=override_prompt,
        command=valid_command,
        interface=sampled_from(["stdio", "file"]),
        timeout=integers(min_value=1, max_value=3600)
    )
    @settings(max_examples=100)
    def test_valid_yaml_parsing_extracts_metadata_correctly(
        self, 
        plugin_name, 
        plugin_version, 
        plugin_description,
        command, 
        interface, 
        timeout
    ):
        """
        有効なプラグインYAMLに対して、メタデータが正確に抽出されることを検証
        """
        plugin_data = {
            "plugin": {
                "name": plugin_name,
                "version": plugin_version,
                "description": plugin_description
            },
            "bridge": {
                "command": command,
                "interface": interface,
                "timeout": timeout
            }
        }
        
        plugin_file = self.temp_path / "test_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        # Load should succeed
        plugin = self.loader.load(plugin_file)
        
        # Metadata should be extracted correctly
        self.assertIsInstance(plugin, Plugin)
        self.assertEqual(plugin.metadata.name, plugin_name)
        self.assertEqual(plugin.metadata.version, plugin_version)
        self.assertEqual(plugin.metadata.description, plugin_description)
        
        # Bridge config should be extracted correctly
        self.assertEqual(plugin.bridge.command, command)
        self.assertEqual(plugin.bridge.interface, interface)
        self.assertEqual(plugin.bridge.timeout, timeout)

    @given(
        plugin_name=valid_plugin_name,
        command=valid_command,
        interface=sampled_from(["stdio", "file"]),
        melchior_override=override_prompt,
        balthasar_override=override_prompt,
        casper_override=override_prompt
    )
    @settings(max_examples=100)
    def test_agent_overrides_extracted_correctly(
        self,
        plugin_name,
        command,
        interface,
        melchior_override,
        balthasar_override,
        casper_override
    ):
        """
        agent_overridesが正しく抽出され、各PersonaTypeにマッピングされることを検証
        """
        plugin_data = {
            "plugin": {
                "name": plugin_name,
            },
            "bridge": {
                "command": command,
                "interface": interface,
            },
            "agent_overrides": {
                "melchior": melchior_override,
                "balthasar": balthasar_override,
                "casper": casper_override
            }
        }
        
        plugin_file = self.temp_path / "test_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        plugin = self.loader.load(plugin_file)
        
        # All three agent overrides should be present
        self.assertEqual(len(plugin.agent_overrides), 3)
        self.assertEqual(plugin.agent_overrides[PersonaType.MELCHIOR], melchior_override)
        self.assertEqual(plugin.agent_overrides[PersonaType.BALTHASAR], balthasar_override)
        self.assertEqual(plugin.agent_overrides[PersonaType.CASPER], casper_override)

    @given(
        plugin_name=valid_plugin_name,
        command=valid_command,
        interface=sampled_from(["stdio", "file"])
    )
    @settings(max_examples=50)
    def test_default_values_applied_when_optional_fields_missing(
        self,
        plugin_name,
        command,
        interface
    ):
        """
        オプションフィールドが省略された場合、デフォルト値が適用されることを検証
        """
        plugin_data = {
            "plugin": {
                "name": plugin_name,
                # version and description are optional
            },
            "bridge": {
                "command": command,
                "interface": interface,
                # timeout is optional
            }
            # agent_overrides is optional
        }
        
        plugin_file = self.temp_path / "test_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        plugin = self.loader.load(plugin_file)
        
        # Default values should be applied
        self.assertEqual(plugin.metadata.version, "1.0.0")
        self.assertEqual(plugin.metadata.description, "")
        self.assertEqual(plugin.bridge.timeout, 30)
        self.assertEqual(plugin.agent_overrides, {})

    @given(
        plugin_name=valid_plugin_name,
        command=valid_command,
        interface=sampled_from(["stdio", "file"])
    )
    @settings(max_examples=50)
    def test_yaml_roundtrip_preserves_data(
        self,
        plugin_name,
        command,
        interface
    ):
        """
        YAML経由のラウンドトリップでデータが保持されることを検証
        """
        original_data = {
            "plugin": {
                "name": plugin_name,
            },
            "bridge": {
                "command": command,
                "interface": interface,
            }
        }
        
        # Write to file
        plugin_file = self.temp_path / "test_plugin.yaml"
        plugin_file.write_text(yaml.dump(original_data))
        
        # Load
        plugin = self.loader.load(plugin_file)
        
        # Verify data integrity
        self.assertEqual(plugin.metadata.name, plugin_name)
        self.assertEqual(plugin.bridge.command, command)
        self.assertEqual(plugin.bridge.interface, interface)


class TestPluginLoaderProperty14(unittest.TestCase):
    """
    **Feature: magi-core, Property 14: 無効なYAMLのエラーハンドリング**
    
    *For any* 無効なYAML形式に対して、具体的なエラー箇所を示すエラーメッセージが生成される
    
    **Validates: Requirements 8.3**
    """

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.temp_path = Path(self.tmpdir.name)
        self.loader = PluginLoader()

    def tearDown(self):
        self.tmpdir.cleanup()

    @given(
        random_text=text(min_size=1, max_size=50, alphabet='abcdefghijklmnopqrstuvwxyz0123456789')
    )
    @settings(max_examples=50)
    def test_syntactically_invalid_yaml_raises_error(self, random_text):
        """
        構文的に無効なYAMLがMagiExceptionを発生させることを検証
        """
        # Create invalid YAML content
        invalid_yaml = f"{{invalid: yaml: {random_text}:"
        
        plugin_file = self.temp_path / "invalid_plugin.yaml"
        plugin_file.write_text(invalid_yaml)
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        # Verify error code and message
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("Failed to parse plugin YAML", cm.exception.error.message)

    def test_missing_plugin_section_raises_error(self):
        """
        'plugin'セクションが欠けている場合のエラーハンドリングを検証
        """
        plugin_data = {
            # Missing 'plugin' section
            "bridge": {
                "command": "some_command",
                "interface": "stdio"
            }
        }
        
        plugin_file = self.temp_path / "missing_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("Missing or invalid 'plugin' section", cm.exception.error.message)

    def test_missing_bridge_section_raises_error(self):
        """
        'bridge'セクションが欠けている場合のエラーハンドリングを検証
        """
        plugin_data = {
            "plugin": {
                "name": "test_plugin"
            }
            # Missing 'bridge' section
        }
        
        plugin_file = self.temp_path / "missing_bridge.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("Missing or invalid 'bridge' section", cm.exception.error.message)

    def test_missing_required_name_raises_error(self):
        """
        必須フィールド'name'が欠けている場合のエラーハンドリングを検証
        """
        plugin_data = {
            "plugin": {
                # Missing 'name'
                "version": "1.0.0"
            },
            "bridge": {
                "command": "some_command",
                "interface": "stdio"
            }
        }
        
        plugin_file = self.temp_path / "missing_name.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("name", cm.exception.error.message.lower())

    @given(interface=text(min_size=1, max_size=20).filter(
        lambda s: s not in ["stdio", "file"]
    ))
    @settings(max_examples=30)
    def test_invalid_interface_value_raises_error(self, interface):
        """
        無効なinterface値がエラーを発生させることを検証
        """
        plugin_data = {
            "plugin": {
                "name": "test_plugin"
            },
            "bridge": {
                "command": "some_command",
                "interface": interface  # Invalid value
            }
        }
        
        plugin_file = self.temp_path / "invalid_interface.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("interface", cm.exception.error.message.lower())

    @given(timeout=integers(max_value=0))
    @settings(max_examples=30)
    def test_invalid_timeout_value_raises_error(self, timeout):
        """
        無効なtimeout値（0以下）がエラーを発生させることを検証
        """
        plugin_data = {
            "plugin": {
                "name": "test_plugin"
            },
            "bridge": {
                "command": "some_command",
                "interface": "stdio",
                "timeout": timeout  # Invalid value (<= 0)
            }
        }
        
        plugin_file = self.temp_path / "invalid_timeout.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("timeout", cm.exception.error.message.lower())

    def test_nonexistent_file_raises_error(self):
        """
        存在しないファイルがMagiExceptionを発生させることを検証
        """
        nonexistent_file = self.temp_path / "does_not_exist.yaml"
        
        with self.assertRaises(MagiException) as cm:
            self.loader.load(nonexistent_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("not found", cm.exception.error.message.lower())

    @given(
        invalid_persona=sampled_from([
            "unknown", "melchior1", "BALTHASAR2", "caspar", 
            "agent", "smith", "neo", "morpheus", "trinity"
        ])
    )
    @settings(max_examples=30)
    def test_invalid_persona_name_in_overrides_is_ignored(self, invalid_persona):
        """
        無効なペルソナ名が無視されることを検証
        """
        plugin_data = {
            "plugin": {
                "name": "test_plugin"
            },
            "bridge": {
                "command": "some_command",
                "interface": "stdio"
            },
            "agent_overrides": {
                invalid_persona: "some override text"
            }
        }
        
        plugin_file = self.temp_path / "invalid_persona.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))
        
        # Should NOT raise exception, invalid keys should be ignored
        plugin = self.loader.load(plugin_file)
        
        # Verify that the loaded plugin overrides don't contain any entries
        # since the only provided override was invalid
        self.assertEqual(plugin.agent_overrides, {})


if __name__ == '__main__':
    unittest.main()
