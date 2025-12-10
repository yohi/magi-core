import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
import sys
from string import ascii_letters, digits

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hypothesis import given, settings
from hypothesis.strategies import text, sampled_from, integers

from magi.plugins.loader import PluginLoader
from magi.errors import MagiException, ErrorCode
from magi.models import PersonaType


def _valid_hash() -> str:
    return "sha256:" + ("a" * 64)


class TestPluginLoaderProperty(unittest.TestCase):
    """Property テスト: PluginLoader のパースとバリデーション。"""

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.temp_path = Path(self.tmpdir.name)
        self.loader = PluginLoader()

    def tearDown(self) -> None:
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
            alphabet=ascii_letters + digits + "-_./",
        ),
        interface=sampled_from(["stdio", "file"]),
        timeout=integers(min_value=1, max_value=300),
        melchior_override=text(min_size=0, max_size=100),
        balthasar_override=text(min_size=0, max_size=100),
        casper_override=text(min_size=0, max_size=100),
    )
    @settings(max_examples=50)
    def test_yaml_parsing_and_metadata_extraction(
        self,
        plugin_name,
        plugin_version,
        plugin_description,
        command,
        interface,
        timeout,
        melchior_override,
        balthasar_override,
        casper_override,
    ):
        plugin_data = {
            "plugin": {
                "name": plugin_name,
                "version": plugin_version,
                "description": plugin_description,
                "hash": _valid_hash(),
            },
            "bridge": {
                "command": command,
                "interface": interface,
                "timeout": timeout,
            },
            "agent_overrides": {
                "melchior": melchior_override,
                "balthasar": balthasar_override,
                "casper": casper_override,
            },
        }

        plugin_file = self.temp_path / "property_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data), encoding="utf-8")

        plugin = self.loader.load(plugin_file)

        self.assertEqual(plugin.metadata.name, plugin_name)
        self.assertEqual(plugin.metadata.version, plugin_version)
        self.assertEqual(plugin.metadata.description, plugin_description)
        self.assertEqual(plugin.bridge.command, command)
        self.assertEqual(plugin.bridge.interface, interface)
        self.assertEqual(plugin.bridge.timeout, timeout)
        self.assertEqual(plugin.agent_overrides[PersonaType.MELCHIOR], melchior_override)
        self.assertEqual(plugin.agent_overrides[PersonaType.BALTHASAR], balthasar_override)
        self.assertEqual(plugin.agent_overrides[PersonaType.CASPER], casper_override)

    # **Feature: magi-core, Property 14: 無効なYAMLのエラーハンドリング**
    # **Validates: Requirements 8.3**
    @given(
        plugin_name=text(min_size=1, max_size=20),
        command=text(min_size=1, max_size=20),
    )
    @settings(max_examples=30)
    def test_missing_sections_raise_errors(self, plugin_name, command):
        plugin_data = {
            "plugin": {
                "name": plugin_name,
                "hash": _valid_hash(),
            },
            # bridge セクションを意図的に欠落させる
        }

        plugin_file = self.temp_path / "missing_section.yaml"
        plugin_file.write_text(yaml.dump(plugin_data), encoding="utf-8")

        with self.assertRaises(MagiException) as cm:
            self.loader.load(plugin_file)

        self.assertEqual(cm.exception.error.code, ErrorCode.PLUGIN_YAML_PARSE_ERROR.value)
        self.assertIn("bridge", cm.exception.error.message)

