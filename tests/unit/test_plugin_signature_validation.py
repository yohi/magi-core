import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from magi.errors import ErrorCode, MagiException
from magi.plugins.loader import PluginLoader
from magi.plugins.signature import PluginSignatureValidator


def _generate_rsa_key_pair():
    """RSA鍵ペアを生成して返す。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )
    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )
    return private_key, public_pem, private_pem


def _canonical_bytes(plugin_data: dict) -> bytes:
    """署名対象の正規化バイト列を生成する。"""
    content_without_sig = yaml.dump(plugin_data, sort_keys=False, allow_unicode=True)
    return PluginSignatureValidator.canonicalize(content_without_sig)


class TestPluginSignatureValidation(unittest.TestCase):
    """プラグイン署名検証のユニットテスト。"""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.base_path = Path(self.tmpdir.name)
        self.validator = PluginSignatureValidator()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_public_key(self, public_pem: bytes) -> Path:
        """公開鍵を一時ファイルに保存する。"""
        pub_path = self.base_path / "pubkey.pem"
        pub_path.write_text(public_pem.decode("utf-8"), encoding="utf-8")
        return pub_path

    def _write_plugin_file(self, plugin_data: dict) -> Path:
        """プラグインYAMLを一時ファイルに保存する。"""
        plugin_path = self.base_path / "plugin.yaml"
        plugin_path.write_text(yaml.dump(plugin_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return plugin_path

    def test_signature_verification_succeeds(self):
        """正しい署名と公開鍵で検証に成功することを確認する。"""
        private_key, public_pem, _ = _generate_rsa_key_pair()
        plugin_data = {
            "plugin": {
                "name": "secure-plugin",
                "version": "1.0.0",
                "description": "署名付きプラグイン",
                "hash": "sha256:" + ("a" * 64),
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

        plugin_path = self._write_plugin_file(plugin_data)
        pub_path = self._write_public_key(public_pem)

        loader = PluginLoader(public_key_path=pub_path)
        plugin = loader.load(plugin_path)

        self.assertEqual(plugin.metadata.signature, plugin_data["plugin"]["signature"])

    def test_tampered_content_is_blocked(self):
        """署名後に改ざんされた場合に検証が失敗することを確認する。"""
        private_key, public_pem, _ = _generate_rsa_key_pair()
        plugin_data = {
            "plugin": {
                "name": "secure-plugin",
                "version": "1.0.0",
                "description": "元の説明",
                "hash": "sha256:" + ("b" * 64),
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

        plugin_path = self._write_plugin_file(plugin_data)
        # 改ざん: 説明文を変更する
        tampered_text = plugin_path.read_text(encoding="utf-8").replace("元の説明", "改ざんされた説明")
        plugin_path.write_text(tampered_text, encoding="utf-8")
        pub_path = self._write_public_key(public_pem)

        loader = PluginLoader(public_key_path=pub_path)

        with self.assertRaises(MagiException) as cm:
            loader.load(plugin_path)

        self.assertEqual(cm.exception.error.code, ErrorCode.SIGNATURE_VERIFICATION_FAILED.value)

    def test_wrong_public_key_is_rejected(self):
        """異なる公開鍵で検証すると失敗することを確認する。"""
        signing_key, _, _ = _generate_rsa_key_pair()
        _, wrong_pub_pem, _ = _generate_rsa_key_pair()
        plugin_data = {
            "plugin": {
                "name": "secure-plugin",
                "version": "1.0.0",
                "description": "鍵不一致テスト",
                "hash": "sha256:" + ("c" * 64),
            },
            "bridge": {"command": "echo", "interface": "stdio", "timeout": 5},
        }

        canonical = _canonical_bytes(plugin_data)
        signature = signing_key.sign(
            canonical,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        plugin_data["plugin"]["signature"] = base64.b64encode(signature).decode("ascii")

        plugin_path = self._write_plugin_file(plugin_data)
        pub_path = self._write_public_key(wrong_pub_pem)

        loader = PluginLoader(public_key_path=pub_path)

        with self.assertRaises(MagiException) as cm:
            loader.load(plugin_path)

        self.assertEqual(cm.exception.error.code, ErrorCode.SIGNATURE_VERIFICATION_FAILED.value)

    def test_hash_only_legacy_is_accepted(self):
        """署名なしハッシュのみのレガシー形式が後方互換で通過することを確認する。"""
        plugin_data = {
            "plugin": {
                "name": "legacy-plugin",
                "version": "0.9.0",
                "description": "レガシープラグイン",
                "hash": "sha256:" + ("d" * 64),
            },
            "bridge": {"command": "echo", "interface": "stdio", "timeout": 5},
        }

        plugin_path = self._write_plugin_file(plugin_data)
        loader = PluginLoader(public_key_path=None)

        plugin = loader.load(plugin_path)

        self.assertEqual(plugin.metadata.name, "legacy-plugin")


if __name__ == "__main__":  # pragma: no cover - unittest実行用
    unittest.main()
