import asyncio
import threading
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
from magi.plugins.signature import SignatureVerificationResult


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
        self.assertIn("signature or plugin.hash", cm.exception.error.message.lower())

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
        error_message = cm.exception.error.message.lower()
        self.assertTrue("plugin" in error_message or "bridge" in error_message)


class TestPluginLoaderAsync(unittest.IsolatedAsyncioTestCase):
    """非同期ロードの基本動作を検証する"""

    class _StubSignatureValidator:
        def __init__(self):
            self.thread_ids = []

        def verify_signature(self, content, signature_b64, public_key_path):
            self.thread_ids.append(threading.get_ident())
            return SignatureVerificationResult(
                ok=False,
                mode="signature",
                key_path=public_key_path,
                reason="invalid_signature",
            )

        def verify_hash(self, content, digest):
            self.thread_ids.append(threading.get_ident())
            return SignatureVerificationResult(
                ok=False,
                mode="hash",
                key_path=None,
                reason="invalid_hash",
            )

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.temp_path = Path(self.tmpdir.name)
        self.loader = PluginLoader()

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_load_async_logs_start_and_complete(self):
        """load_async が正常に読み込み、開始/完了ログを残す"""
        plugin_data = {
            "plugin": {
                "name": "async_plugin",
                "hash": "sha256:" + ("d" * 64),
            },
            "bridge": {
                "command": "echo",
                "interface": "stdio",
            },
        }
        plugin_file = self.temp_path / "async_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        with self.assertLogs("magi.plugins.loader", level="INFO") as cm:
            plugin = await self.loader.load_async(plugin_file)

        self.assertEqual(plugin.metadata.name, "async_plugin")
        logs = "\n".join(cm.output)
        self.assertIn("plugin.load.started", logs)
        self.assertIn("plugin.load.completed", logs)

    async def test_load_all_async_loads_multiple_plugins(self):
        """複数プラグインを非同期で読み込めること"""
        plugin_data_1 = {
            "plugin": {
                "name": "plugin_one",
                "hash": "sha256:" + ("e" * 64),
            },
            "bridge": {
                "command": "python3",
                "interface": "stdio",
            },
        }
        plugin_data_2 = {
            "plugin": {
                "name": "plugin_two",
                "hash": "sha256:" + ("f" * 64),
            },
            "bridge": {
                "command": "/usr/bin/python3",
                "interface": "stdio",
            },
        }

        file_one = self.temp_path / "one.yaml"
        file_two = self.temp_path / "two.yaml"
        file_one.write_text(yaml.dump(plugin_data_1))
        file_two.write_text(yaml.dump(plugin_data_2))

        results = await self.loader.load_all_async([file_one, file_two])

        self.assertEqual(len(results), 2)
        # 成功ケースでは両方ともPluginオブジェクトであることを確認
        self.assertIsInstance(results[0], Plugin)
        self.assertIsInstance(results[1], Plugin)
        self.assertEqual(results[0].metadata.name, "plugin_one")
        self.assertEqual(results[1].metadata.name, "plugin_two")

    async def test_load_async_signature_failure_offloaded_and_logged(self):
        """署名検証失敗が別スレッドで行われ、ログが記録される"""
        stub_validator = self._StubSignatureValidator()
        loader = PluginLoader(signature_validator=stub_validator)

        plugin_data = {
            "plugin": {
                "name": "signed-plugin",
                "signature": "invalid-base64",
            },
            "bridge": {
                # PluginGuard が拒否しない安全なコマンドを使用する
                "command": "echo",
                "interface": "stdio",
            },
        }
        plugin_file = self.temp_path / "signed_plugin.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        main_thread = threading.get_ident()

        with self.assertLogs("magi.plugins.loader", level="INFO") as cm:
            with self.assertRaises(MagiException) as err:
                await loader.load_async(plugin_file)

        self.assertEqual(err.exception.error.code, ErrorCode.SIGNATURE_VERIFICATION_FAILED.value)
        self.assertTrue(stub_validator.thread_ids)
        self.assertNotEqual(main_thread, stub_validator.thread_ids[0])

        logs = "\n".join(cm.output)
        self.assertIn("plugin.load.signature_failed", logs)

    async def test_load_async_timeout_is_isolated(self):
        """タイムアウトしたプラグインが他のロードを妨げないこと"""

        class SlowLoader(PluginLoader):
            async def _load_async_impl(self, path: Path) -> Plugin:
                if "slow" in path.name:
                    await asyncio.sleep(0.05)
                return await super()._load_async_impl(path)

        loader = SlowLoader()

        slow_plugin = {
            "plugin": {"name": "slow_plugin", "hash": "sha256:" + ("1" * 64)},
            "bridge": {"command": "echo", "interface": "stdio"},
        }
        fast_plugin = {
            "plugin": {"name": "fast_plugin", "hash": "sha256:" + ("2" * 64)},
            "bridge": {"command": "echo", "interface": "stdio"},
        }

        slow_file = self.temp_path / "slow.yaml"
        fast_file = self.temp_path / "fast.yaml"
        slow_file.write_text(yaml.dump(slow_plugin))
        fast_file.write_text(yaml.dump(fast_plugin))

        with self.assertLogs("magi.plugins.loader", level="ERROR") as cm:
            results = await loader.load_all_async(
                [slow_file, fast_file],
                timeout=0.01,
            )

        self.assertEqual(len(results), 2)
        self.assertIsInstance(results[0], MagiException)
        self.assertEqual(results[0].error.code, ErrorCode.PLUGIN_LOAD_TIMEOUT.value)
        self.assertIsInstance(results[1], Plugin)
        self.assertEqual(results[1].metadata.name, "fast_plugin")

        logs = "\n".join(cm.output)
        self.assertIn("plugin.load.timeout", logs)

    async def test_load_all_async_isolates_failures(self):
        """1つのプラグインのロード失敗が他のプラグインに影響しないこと"""
        # 1つ目は正常なプラグイン
        plugin_data_1 = {
            "plugin": {
                "name": "valid_plugin",
                "hash": "sha256:" + ("a" * 64),
            },
            "bridge": {
                "command": "python3",
                "interface": "stdio",
            },
        }
        file_one = self.temp_path / "valid.yaml"
        file_one.write_text(yaml.dump(plugin_data_1))

        # 2つ目は存在しないファイル
        file_two = self.temp_path / "nonexistent.yaml"

        # 3つ目は無効なYAML
        file_three = self.temp_path / "invalid.yaml"
        file_three.write_text("{invalid yaml:")

        results = await self.loader.load_all_async([file_one, file_two, file_three])

        self.assertEqual(len(results), 3)

        # 1つ目は成功
        self.assertIsInstance(results[0], Plugin)
        self.assertEqual(results[0].metadata.name, "valid_plugin")

        # 2つ目と3つ目は例外
        self.assertIsInstance(results[1], Exception)
        self.assertIsInstance(results[2], Exception)

        # 例外がMagiExceptionであることを確認
        self.assertIsInstance(results[1], MagiException)
        self.assertIsInstance(results[2], MagiException)
