import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
import sys
from string import ascii_letters, digits

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hypothesis import given, settings
from hypothesis.strategies import text, dictionaries, sampled_from, integers

from magi.plugins.loader import PluginLoader, PluginMetadata, BridgeConfig, Plugin, ValidationResult
from magi.errors import MagiException, ErrorCode
from magi.models import PersonaType


def _build_invalid_yaml(text_value: str) -> str:
    """無効なYAML文字列を生成する"""
    return "{" + text_value + ":"

class TestPluginLoader(unittest.TestCase):

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.temp_path = Path(self.tmpdir.name)
        self.loader = PluginLoader()

    def tearDown(self):
        self.tmpdir.cleanup()

    # **Feature: magi-core, Property 13: YAMLパースとメタデータ抽出**
    # **Validates: Requirements 8.1, 8.2**
    @given(
        plugin_name=text(min_size=1, max_size=20),
        plugin_version=text(min_size=1, max_size=10),
        plugin_description=text(min_size=0, max_size=50),
        command=text(
            min_size=1,
            max_size=30,
            alphabet=ascii_letters + digits + "-_./"
        ),
        interface=sampled_from(["stdio", "file"]),
        timeout=integers(min_value=1, max_value=300),
        melchior_override=text(min_size=0, max_size=100),
        balthasar_override=text(min_size=0, max_size=100),
        casper_override=text(min_size=0, max_size=100)
    )
    @settings(max_examples=100)
    def test_yaml_parsing_and_metadata_extraction(self, plugin_name, plugin_version, plugin_description,
                                                command, interface, timeout,
                                                melchior_override, balthasar_override, casper_override):
        
        # Construct valid plugin YAML data
        plugin_data = {
            "plugin": {
                "name": plugin_name,
                "version": plugin_version,
                "description": plugin_description,
                "hash": "sha256:" + ("a" * 64),
            },
            "bridge": {
                "command": command,
                "interface": interface,
                "timeout": timeout
            },
            "agent_overrides": {
                "melchior": melchior_override,
                "balthasar": balthasar_override,
                "casper": casper_override
            }
        }
        
        # Create a temporary plugin file
        plugin_file = self.temp_path / "test_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        # Load the plugin
        plugin = self.loader.load(plugin_file)

        # Assert metadata
        self.assertEqual(plugin.metadata.name, plugin_name)
        self.assertEqual(plugin.metadata.version, plugin_version)
        self.assertEqual(plugin.metadata.description, plugin_description)

        # Assert bridge config
        self.assertEqual(plugin.bridge.command, command)
        self.assertEqual(plugin.bridge.interface, interface)
        self.assertEqual(plugin.bridge.timeout, timeout)

        # Assert agent overrides
        self.assertEqual(plugin.agent_overrides[PersonaType.MELCHIOR], melchior_override)
        self.assertEqual(plugin.agent_overrides[PersonaType.BALTHASAR], balthasar_override)
        self.assertEqual(plugin.agent_overrides[PersonaType.CASPER], casper_override)

    # Test cases for default values
    @given(
        plugin_name=text(min_size=1, max_size=20),
        command=text(
            min_size=1,
            max_size=30,
            alphabet=ascii_letters + digits + "-_./"
        ),
        interface=sampled_from(["stdio", "file"]),
    )
    @settings(max_examples=20)
    def test_default_values_applied_correctly(self, plugin_name, command, interface):
        plugin_data = {
            "plugin": {
                "name": plugin_name,
                "hash": "sha256:" + ("b" * 64),
            },
            "bridge": {
                "command": command,
                "interface": interface,
            }
            # No version, description, timeout, agent_overrides
        }

        plugin_file = self.temp_path / "test_plugin_defaults.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        plugin = self.loader.load(plugin_file)

        self.assertEqual(plugin.metadata.name, plugin_name)
        self.assertEqual(plugin.metadata.version, "1.0.0")  # Default version
        self.assertEqual(plugin.metadata.description, "")    # Default description
        self.assertEqual(plugin.bridge.command, command)
        self.assertEqual(plugin.bridge.interface, interface)
        self.assertEqual(plugin.bridge.timeout, 30)          # Default timeout
        self.assertEqual(plugin.agent_overrides, {})       # Default empty dict

    def test_missing_signature_or_hash_is_rejected(self):
        """署名またはハッシュが欠落したプラグインは拒否される"""
        plugin_data = {
            "plugin": {
                "name": "example",
                "version": "1.0.0",
                "description": "desc",
            },
            "bridge": {
                "command": "echo",
                "interface": "stdio",
                "timeout": 10,
            },
        }

        plugin_file = self.temp_path / "missing_security.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)

        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("signature", cm.exception.error.message.lower())

    def test_command_with_meta_characters_is_rejected(self):
        """メタ文字を含むコマンドは無効として扱われる"""
        plugin_data = {
            "plugin": {
                "name": "danger",
                "version": "1.0.0",
                "hash": "sha256:" + ("c" * 64),
            },
            "bridge": {
                "command": "rm -rf /",  # 意図的にメタ文字を含む
                "interface": "stdio",
            }
        }

        plugin_file = self.temp_path / "invalid_command.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)

        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)

    # **Feature: magi-core, Property 14: 無効なYAMLのエラーハンドリング**
    # **Validates: Requirements 8.3**
    @given(invalid_yaml_content=text(min_size=1, max_size=100).map(_build_invalid_yaml))
    @settings(max_examples=50)
    def test_invalid_yaml_error_handling(self, invalid_yaml_content):
        plugin_file = self.temp_path / "invalid_plugin.yaml"
        plugin_file.write_text(invalid_yaml_content)

        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("Failed to parse plugin YAML", cm.exception.error.message)

    @given(
        valid_yaml_content=dictionaries(
            keys=text(min_size=1, max_size=10),
            values=text(min_size=1, max_size=10),
            min_size=1
        ).map(yaml.dump).filter(lambda s: "plugin" not in yaml.safe_load(s) or "bridge" not in yaml.safe_load(s))
    )
    @settings(max_examples=50)
    def test_missing_required_sections_error_handling(self, valid_yaml_content):
        # This strategy generates valid YAML but might be missing 'plugin' or 'bridge' sections
        # which our validate method explicitly checks for.
        plugin_file = self.temp_path / "missing_sections_plugin.yaml"
        plugin_file.write_text(valid_yaml_content)

        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)
        
        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        # We need to check for either of the two missing sections errors.
        # This is a bit brittle, but Hypothesis might generate only one type of error at a time.
        error_message = cm.exception.error.message
        self.assertTrue("Missing or invalid 'plugin' section" in error_message or
                        "Missing or invalid 'bridge' section" in error_message)
