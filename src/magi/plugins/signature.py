"""プラグイン署名検証ユーティリティ."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

logger = logging.getLogger(__name__)


@dataclass
class SignatureVerificationResult:
    """署名またはハッシュ検証の結果."""

    ok: bool
    mode: str
    key_path: Optional[Path] = None
    reason: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    legacy: bool = False


class PluginSignatureValidator:
    """プラグイン定義の署名/ハッシュ検証を行うクラス."""

    def __init__(
        self,
        public_key_path: Optional[Path] = None,
        fallback_public_key_pem: Optional[str] = None,
    ) -> None:
        self.public_key_path = public_key_path
        self.fallback_public_key_pem = fallback_public_key_pem

    @staticmethod
    def canonicalize(content: str) -> bytes:
        """署名検証用の正規化バイト列を返す.

        - CRLF を LF に変換
        - plugin.signature を除去して自己参照を防止
        - yaml.safe_dump でキー順を安定化
        """
        try:
            loaded = yaml.safe_load(content) or {}
        except Exception:
            normalized = content.replace("\r\n", "\n").strip()
            return normalized.encode("utf-8")

        if isinstance(loaded, dict):
            loaded = dict(loaded)
            plugin_section = loaded.get("plugin")
            if isinstance(plugin_section, dict):
                plugin_section = dict(plugin_section)
                plugin_section.pop("signature", None)
                loaded["plugin"] = plugin_section

        canonical_yaml = yaml.safe_dump(
            loaded,
            sort_keys=True,
            allow_unicode=True,
        )
        normalized = canonical_yaml.replace("\r\n", "\n").strip()
        return normalized.encode("utf-8")

    def _load_public_key(self, public_key_path: Optional[Path]) -> Tuple[Optional[object], Optional[Path]]:
        """公開鍵をロードし、鍵オブジェクトと使用したパスを返す."""
        if public_key_path and public_key_path.exists():
            pem = public_key_path.read_text(encoding="utf-8")
            try:
                key = serialization.load_pem_public_key(pem.encode("utf-8"))
                logger.info("plugin.signature.public_key_loaded path=%s", public_key_path)
                return key, public_key_path
            except Exception as exc:
                logger.warning("plugin.signature.public_key_load_failed path=%s error=%s", public_key_path, exc)
                return None, public_key_path

        if self.fallback_public_key_pem:
            try:
                key = serialization.load_pem_public_key(self.fallback_public_key_pem.encode("utf-8"))
                logger.info("plugin.signature.fallback_public_key_loaded")
                return key, None
            except Exception as exc:
                logger.warning("plugin.signature.fallback_public_key_load_failed error=%s", exc)

        return None, public_key_path

    def verify_signature(
        self,
        content: str,
        signature_b64: str,
        public_key_path: Optional[Path],
    ) -> SignatureVerificationResult:
        """署名を検証する."""
        payload = self.canonicalize(content)
        key, resolved_path = self._load_public_key(public_key_path)
        if key is None:
            return SignatureVerificationResult(
                ok=False,
                mode="signature",
                key_path=resolved_path,
                reason="public_key_not_found",
            )

        try:
            signature = base64.b64decode(signature_b64)
        except Exception:
            return SignatureVerificationResult(
                ok=False,
                mode="signature",
                key_path=resolved_path,
                reason="invalid_signature_encoding",
            )

        try:
            if isinstance(key, rsa.RSAPublicKey):
                key.verify(
                    signature,
                    payload,
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                    hashes.SHA256(),
                )
            elif isinstance(key, ec.EllipticCurvePublicKey):
                key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
            else:
                return SignatureVerificationResult(
                    ok=False,
                    mode="signature",
                    key_path=resolved_path,
                    reason="unsupported_public_key_type",
                )
        except InvalidSignature:
            return SignatureVerificationResult(
                ok=False,
                mode="signature",
                key_path=resolved_path,
                reason="invalid_signature",
            )
        except Exception as exc:
            return SignatureVerificationResult(
                ok=False,
                mode="signature",
                key_path=resolved_path,
                reason=f"verify_error:{exc}",
            )

        return SignatureVerificationResult(ok=True, mode="signature", key_path=resolved_path)

    def verify_hash(self, content: str, digest: str) -> SignatureVerificationResult:
        """ハッシュ(sha256)の検証を行う."""
        if not digest.startswith("sha256:"):
            return SignatureVerificationResult(
                ok=False,
                mode="hash",
                reason="unsupported_hash_scheme",
                legacy=True,
            )

        payload = self.canonicalize(content)
        expected = digest.split(":", 1)[1].lower()
        actual = hashlib.sha256(payload).hexdigest()

        return SignatureVerificationResult(
            ok=actual == expected,
            mode="hash",
            expected=expected,
            actual=actual,
            legacy=True,
        )


__all__ = ["PluginSignatureValidator", "SignatureVerificationResult"]
