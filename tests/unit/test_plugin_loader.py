import asyncio
import base64
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional
import yaml
import sys
from string import ascii_letters, digits

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hypothesis import given, settings
from hypothesis.strategies import text, dictionaries, sampled_from, integers

from magi.config.settings import MagiSettings
from magi.plugins.loader import PluginLoader, PluginMetadata, BridgeConfig, Plugin, ValidationResult
from magi.plugins.permission_guard import PluginPermissionGuard
from magi.errors import MagiException, ErrorCode
from magi.models import PersonaType
from magi.plugins.signature import PluginSignatureValidator, SignatureVerificationResult
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _build_invalid_yaml(text_value: str) -> str:
    """無効なYAML文字列を生成する"""
    return "{" + text_value + ":"


def _generate_rsa_key_pair():
    """RSA鍵ペアを生成して返す"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


def _canonical_bytes(plugin_data: dict) -> bytes:
    """署名対象の正規化バイト列を生成する"""
    content_without_sig = yaml.dump(plugin_data, sort_keys=False, allow_unicode=True)
    return PluginSignatureValidator.canonicalize(content_without_sig)

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

    def test_agent_overrides_are_cleared_when_permission_denied(self):
        """権限が無効な場合は agent_overrides が適用されない"""
        settings = MagiSettings(api_key="dummy-key")
        loader = PluginLoader(config=settings, permission_guard=PluginPermissionGuard(settings))

        plugin_data = {
            "plugin": {
                "name": "denied-plugin",
                "hash": "sha256:" + ("d" * 64),
            },
            "bridge": {
                "command": "echo",
                "interface": "stdio",
            },
            "agent_overrides": {
                "melchior": "override-1",
                "balthasar": "override-2",
            },
        }

        plugin_file = self.temp_path / "denied.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        with self.assertLogs("magi.plugins.permission_guard", level="WARNING") as cm:
            plugin = loader.load(plugin_file)

        self.assertEqual(plugin.agent_overrides, {})
        logs = "\n".join(cm.output)
        self.assertIn("plugin.override.denied", logs)

    def test_agent_overrides_are_kept_when_trusted_and_allowed(self):
        """信頼済み署名かつ許可設定時は agent_overrides が反映される"""

        class _AllowSignatureValidator:
            def verify_signature(self, content, signature_b64, public_key_path):
                return SignatureVerificationResult(
                    ok=True,
                    mode="signature",
                    key_path=public_key_path,
                    reason=None,
                )

            def verify_hash(self, content, digest):
                return SignatureVerificationResult(
                    ok=True,
                    mode="hash",
                    key_path=None,
                    reason=None,
                )

        settings = MagiSettings(
            api_key="dummy-key",
            plugin_prompt_override_allowed=True,
            plugin_trusted_signatures=["trusted-signature"],
        )
        loader = PluginLoader(
            config=settings,
            permission_guard=PluginPermissionGuard(settings),
            signature_validator=_AllowSignatureValidator(),
        )

        plugin_data = {
            "plugin": {
                "name": "trusted-plugin",
                "signature": "trusted-signature",
            },
            "bridge": {
                "command": "echo",
                "interface": "stdio",
            },
            "agent_overrides": {
                "melchior": "trusted-override",
                "balthasar": "other-override",
            },
        }

        plugin_file = self.temp_path / "trusted.yaml"
        plugin_file.write_text(yaml.dump(plugin_data))

        with self.assertLogs("magi.plugins.permission_guard", level="INFO") as cm:
            plugin = loader.load(plugin_file)

        self.assertEqual(
            plugin.agent_overrides[PersonaType.MELCHIOR],
            "trusted-override",
        )
        self.assertEqual(
            plugin.agent_overrides[PersonaType.BALTHASAR],
            "other-override",
        )
        logs = "\n".join(cm.output)
        self.assertIn("plugin.override.applied", logs)

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

    def test_production_mode_requires_explicit_public_key_path(self):
        """production_mode 有効時はCWDフォールバックを無効化し、明示パスを要求する"""
        private_key, public_pem = _generate_rsa_key_pair()
        plugin_data = {
            "plugin": {
                "name": "prod-secure-plugin",
                "version": "1.0.0",
                "description": "production mode",
                "hash": "sha256:" + ("e" * 64),
            },
            "bridge": {"command": "echo", "interface": "stdio", "timeout": 5},
        }
        canonical = _canonical_bytes(plugin_data)
        signature = private_key.sign(
            canonical,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        plugin_data["plugin"]["signature"] = base64.b64encode(signature).decode("ascii")

        plugin_file = self.temp_path / "prod_plugin.yaml"
        plugin_file.write_text(
            yaml.dump(plugin_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        plugins_dir = self.temp_path / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        default_key_path = plugins_dir / "public_key.pem"
        default_key_path.write_text(public_pem.decode("utf-8"), encoding="utf-8")

        env_backup = os.environ.get("MAGI_PLUGIN_PUBKEY_PATH")
        os.environ.pop("MAGI_PLUGIN_PUBKEY_PATH", None)
        current_cwd = Path.cwd()
        os.chdir(self.temp_path)
        try:
            config = type(
                "Config",
                (),
                {"plugin_public_key_path": None, "production_mode": True},
            )()
            loader = PluginLoader(config=config)

            with self.assertLogs("magi.plugins.loader", level="INFO") as logs, self.assertRaises(MagiException) as cm:
                loader.load(plugin_file)

            self.assertEqual(cm.exception.error.code, ErrorCode.SIGNATURE_VERIFICATION_FAILED.value)
            self.assertIn("production_mode", cm.exception.error.message)
            log_text = "\n".join(logs.output)
            self.assertIn("plugin.signature.key_path_missing", log_text)
            self.assertIn("production_mode=True", log_text)
            self.assertIn("key_path_ignored", log_text)
        finally:
            os.chdir(current_cwd)
            if env_backup is not None:
                os.environ["MAGI_PLUGIN_PUBKEY_PATH"] = env_backup
            else:
                os.environ.pop("MAGI_PLUGIN_PUBKEY_PATH", None)

    def test_logs_public_key_resolution_source_env(self):
        """公開鍵パス解決元が環境変数であることをログに記録する"""
        private_key, public_pem = _generate_rsa_key_pair()
        plugin_data = {
            "plugin": {
                "name": "env-secure-plugin",
                "version": "1.0.0",
                "description": "env path",
                "hash": "sha256:" + ("f" * 64),
            },
            "bridge": {"command": "echo", "interface": "stdio", "timeout": 5},
        }
        canonical = _canonical_bytes(plugin_data)
        signature = private_key.sign(
            canonical,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        plugin_data["plugin"]["signature"] = base64.b64encode(signature).decode("ascii")

        plugin_file = self.temp_path / "env_plugin.yaml"
        plugin_file.write_text(
            yaml.dump(plugin_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        env_key_path = self.temp_path / "env_pubkey.pem"
        env_key_path.write_text(public_pem.decode("utf-8"), encoding="utf-8")
        env_backup = os.environ.get("MAGI_PLUGIN_PUBKEY_PATH")
        os.environ["MAGI_PLUGIN_PUBKEY_PATH"] = str(env_key_path)

        try:
            config = type(
                "Config",
                (),
                {"plugin_public_key_path": None, "production_mode": False},
            )()
            loader = PluginLoader(config=config)

            with self.assertLogs("magi.plugins.loader", level="INFO") as logs:
                plugin = loader.load(plugin_file)

            self.assertEqual(plugin.metadata.name, "env-secure-plugin")
            log_text = "\n".join(logs.output)
            self.assertIn("source=env", log_text)
            self.assertIn(str(env_key_path), log_text)
        finally:
            if env_backup is not None:
                os.environ["MAGI_PLUGIN_PUBKEY_PATH"] = env_backup
            else:
                os.environ.pop("MAGI_PLUGIN_PUBKEY_PATH", None)


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

    async def test_load_all_async_respects_concurrency_limit(self):
        """同時ロード数制限を超えないこと"""

        class TrackingLoader(PluginLoader):
            def __init__(self):
                super().__init__()
                self.active = 0
                self.max_active = 0

            async def load_async(self, path: Path, *, timeout: Optional[float] = None) -> Plugin:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    await asyncio.sleep(0.05)
                    return Plugin(
                        metadata=PluginMetadata(name=path.stem),
                        bridge=BridgeConfig(command="echo", interface="stdio"),
                        agent_overrides={},
                    )
                finally:
                    self.active -= 1

        loader = TrackingLoader()
        plugin_files = [self.temp_path / f"plugin_{idx}.yaml" for idx in range(3)]

        results = await loader.load_all_async(plugin_files, concurrency_limit=1, timeout=1.0)

        self.assertTrue(all(isinstance(result, Plugin) for result in results))
        self.assertEqual(loader.max_active, 1)

    async def test_load_all_async_logs_waiting_when_limit_reached(self):
        """上限到達時に待機開始/終了がログに残ること"""

        class SlowLoader(PluginLoader):
            async def load_async(self, path: Path, *, timeout: Optional[float] = None) -> Plugin:
                await asyncio.sleep(0.05)
                return Plugin(
                    metadata=PluginMetadata(name=path.stem),
                    bridge=BridgeConfig(command="echo", interface="stdio"),
                    agent_overrides={},
                )

        loader = SlowLoader()

        with self.assertLogs("magi.plugins.loader", level="INFO") as cm:
            results = await loader.load_all_async(
                [self.temp_path / "slow.yaml", self.temp_path / "fast.yaml"],
                concurrency_limit=1,
                timeout=1.0,
            )

        self.assertTrue(all(isinstance(result, Plugin) for result in results))
        logs = "\n".join(cm.output)
        self.assertIn("plugin.load.wait_start", logs)
        self.assertIn("plugin.load.wait_end", logs)

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
