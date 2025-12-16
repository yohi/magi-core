import base64
import tempfile
import unittest
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from magi.config.settings import MagiSettings
from magi.errors import ErrorCode, MagiException
from magi.plugins.loader import PluginLoader
from magi.plugins.signature import PluginSignatureValidator


def _build_signed_plugin_yaml(private_key: rsa.RSAPrivateKey, plugin_data: dict) -> str:
    """プラグイン定義に署名を付与した YAML を生成する。"""
    canonical = PluginSignatureValidator.canonicalize(
        yaml.safe_dump(plugin_data, allow_unicode=True, sort_keys=False)
    )
    signature = private_key.sign(
        canonical,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    plugin_data["plugin"]["signature"] = base64.b64encode(signature).decode("ascii")
    return yaml.safe_dump(plugin_data, allow_unicode=True, sort_keys=False)


class TestPluginLoaderProductionMode(unittest.TestCase):
    """本番運用モードでの公開鍵パス解決を統合検証する。"""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tmpdir.name)

        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _write_plugin_yaml(self, *, include_hash: bool = False) -> Path:
        """テスト用プラグイン YAML を署名付きで書き出す。"""
        plugin_data = {
            "plugin": {
                "name": "prod-plugin",
                "version": "1.0.0",
                "description": "production mode plugin",
            },
            "bridge": {"command": "echo", "interface": "stdio", "timeout": 5},
        }
        if include_hash:
            plugin_data["plugin"]["hash"] = "sha256:" + ("a" * 64)

        signed_yaml = _build_signed_plugin_yaml(self.private_key, plugin_data)
        plugin_file = self.temp_path / "plugin.yaml"
        plugin_file.write_text(signed_yaml, encoding="utf-8")
        return plugin_file

    def test_load_with_explicit_public_key_path_succeeds(self) -> None:
        """production_mode=True かつ明示パス指定時にロード成功し、解決元がログ出力される。"""
        pubkey_path = self.temp_path / "public_key.pem"
        pubkey_path.write_text(self.public_pem.decode("utf-8"), encoding="utf-8")

        plugin_file = self._write_plugin_yaml()

        settings = MagiSettings(
            api_key="test-api-key",
            production_mode=True,
            plugin_public_key_path=pubkey_path,
        )
        loader = PluginLoader(config=settings)

        with self.assertLogs("magi.plugins.loader", level="INFO") as cm:
            plugin = loader.load(plugin_file)

        self.assertEqual(plugin.metadata.name, "prod-plugin")
        logs = "\n".join(cm.output)
        self.assertIn("plugin.signature.key_path_resolved", logs)
        self.assertIn("source=config", logs)
        self.assertIn("production_mode=True", logs)

    def test_load_with_missing_public_key_path_fails(self) -> None:
        """production_mode=True で鍵ファイルが存在しない場合は検証に失敗する。"""
        missing_key_path = self.temp_path / "missing.pem"
        plugin_file = self._write_plugin_yaml()

        settings = MagiSettings(
            api_key="test-api-key",
            production_mode=True,
            plugin_public_key_path=missing_key_path,
        )
        loader = PluginLoader(config=settings)

        with self.assertLogs("magi.plugins.loader", level="INFO") as cm, self.assertRaises(
            MagiException
        ) as err:
            loader.load(plugin_file)

        self.assertEqual(err.exception.error.code, ErrorCode.SIGNATURE_VERIFICATION_FAILED.value)
        logs = "\n".join(cm.output)
        self.assertIn("plugin.signature.key_path_resolved", logs)
        self.assertIn(str(missing_key_path), logs)
        self.assertIn("production_mode=True", logs)


if __name__ == "__main__":
    unittest.main()
