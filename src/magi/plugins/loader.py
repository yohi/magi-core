import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from magi.errors import ErrorCode, MagiException, create_plugin_error
from magi.models import PersonaType
from magi.plugins.guard import PluginGuard
from magi.plugins.signature import PluginSignatureValidator

HASH_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
GUARD = PluginGuard()
LOGGER = logging.getLogger(__name__)

@dataclass
class PluginMetadata:
    name: str
    version: str = "1.0.0"
    description: str = ""
    signature: Optional[str] = None
    hash: Optional[str] = None

@dataclass
class BridgeConfig:
    command: str
    interface: str  # "stdio" | "file"
    timeout: int = 30

@dataclass
class Plugin:
    metadata: PluginMetadata
    bridge: BridgeConfig
    agent_overrides: Dict[PersonaType, str] = field(default_factory=dict)
    signature: Optional[str] = None
    hash: Optional[str] = None

class PluginLoader:
    """YAMLプラグイン定義の読み込みとバリデーション"""

    def __init__(
        self,
        *,
        public_key_path: Optional[Path] = None,
        config: Optional[Any] = None,
        signature_validator: Optional[PluginSignatureValidator] = None,
    ) -> None:
        """初期化

        Args:
            public_key_path: 署名検証に用いる公開鍵パス（優先度最高）
            config: Config または同等のオブジェクト。plugin_public_key_path 属性を参照する
            signature_validator: 検証用のバリデータ（テスト差し替え用）
        """
        self.public_key_path = public_key_path
        self.config = config
        self.signature_validator = signature_validator or PluginSignatureValidator()

    def load(self, path: Path) -> Plugin:
        """YAMLファイルからプラグインを読み込み、パースし、検証する"""
        if not path.exists():
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                f"Plugin file not found: {path}"
            ))
        
        try:
            content = path.read_text(encoding="utf-8")
            plugin_data = self._parse_yaml(content)
        except Exception as e:
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                f"Failed to parse plugin YAML from {path}: {e}"
            )) from e
        
        validation_result = self.validate(plugin_data)
        if not validation_result.is_valid:
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                f"Plugin validation failed for {path}: {', '.join(validation_result.errors)}"
            ))

        self._verify_security(content, plugin_data, path)

        metadata = PluginMetadata(
            name=plugin_data["plugin"]["name"],
            version=plugin_data["plugin"].get("version", "1.0.0"),
            description=plugin_data["plugin"].get("description", ""),
            signature=plugin_data["plugin"].get("signature"),
            hash=plugin_data["plugin"].get("hash"),
        )
        bridge = BridgeConfig(
            command=plugin_data["bridge"]["command"],
            interface=plugin_data["bridge"]["interface"],
            timeout=plugin_data["bridge"].get("timeout", 30)
        )

        agent_overrides: Dict[PersonaType, str] = {}
        if "agent_overrides" in plugin_data:
            for persona_name, override_prompt in plugin_data["agent_overrides"].items():
                try:
                    persona_type = PersonaType[persona_name.upper()]
                    agent_overrides[persona_type] = override_prompt
                except KeyError:
                    # Unknown persona types are ignored
                    pass
        
        return Plugin(
            metadata=metadata,
            bridge=bridge,
            agent_overrides=agent_overrides,
            signature=metadata.signature,
            hash=metadata.hash,
        )

    def validate(self, plugin_data: Dict) -> "ValidationResult":
        """プラグイン定義の妥当性を検証"""
        errors = []

        if not isinstance(plugin_data, dict):
            errors.append("Plugin data must be a dictionary.")
            return ValidationResult(is_valid=False, errors=errors)

        # Validate 'plugin' section
        if "plugin" not in plugin_data or not isinstance(plugin_data["plugin"], dict):
            errors.append("Missing or invalid 'plugin' section.")
        else:
            if "name" not in plugin_data["plugin"] or not isinstance(plugin_data["plugin"]["name"], str):
                errors.append("Plugin 'name' is required and must be a string.")
            if "version" in plugin_data["plugin"] and not isinstance(plugin_data["plugin"]["version"], str):
                errors.append("Plugin 'version' must be a string.")
            if "description" in plugin_data["plugin"] and not isinstance(plugin_data["plugin"]["description"], str):
                errors.append("Plugin 'description' must be a string.")
            signature = plugin_data["plugin"].get("signature")
            digest = plugin_data["plugin"].get("hash")
            if not signature and not digest:
                errors.append("Plugin signature or hash is required.")
            if digest and not HASH_PATTERN.match(digest):
                errors.append("Plugin 'hash' must be sha256:<64hex> format.")

        # Validate 'bridge' section
        if "bridge" not in plugin_data or not isinstance(plugin_data["bridge"], dict):
            errors.append("Missing or invalid 'bridge' section.")
        else:
            if "command" not in plugin_data["bridge"] or not isinstance(plugin_data["bridge"]["command"], str):
                errors.append("Bridge 'command' is required and must be a string.")
            if "interface" not in plugin_data["bridge"] or plugin_data["bridge"]["interface"] not in ["stdio", "file"]:
                errors.append("Bridge 'interface' is required and must be 'stdio' or 'file'.")
            else:
                try:
                    GUARD.validate(plugin_data["bridge"]["command"], [])
                except MagiException as exc:
                    errors.append(exc.error.message)
            if "timeout" in plugin_data["bridge"] and not isinstance(plugin_data["bridge"]["timeout"], int):
                errors.append("Bridge 'timeout' must be an integer.")
            elif "timeout" in plugin_data["bridge"] and plugin_data["bridge"]["timeout"] <= 0:
                errors.append("Bridge 'timeout' must be a positive integer.")

        # Validate 'agent_overrides' section
        if "agent_overrides" in plugin_data:
            if not isinstance(plugin_data["agent_overrides"], dict):
                errors.append("'agent_overrides' must be a dictionary.")
            else:
                for persona_name, override_prompt in plugin_data["agent_overrides"].items():
                    if not isinstance(persona_name, str) or not isinstance(override_prompt, str):
                        errors.append(f"Agent override keys and values must be strings: {persona_name}: {override_prompt}")
                    try:
                        # Check if the persona name is valid
                        PersonaType[persona_name.upper()]
                    except KeyError:
                        # Unknown persona types are allowed here and will be ignored in load()
                        pass


        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _parse_yaml(self, content: str) -> Dict:
        """YAML文字列をパース"""
        return yaml.safe_load(content)

    def _verify_security(self, raw_content: str, plugin_data: Dict[str, Any], path: Path) -> None:
        """署名/ハッシュ検証を実施し、失敗時は例外を送出する。"""
        plugin_section = plugin_data.get("plugin") or {}
        signature = plugin_section.get("signature")
        digest = plugin_section.get("hash")

        if signature:
            key_path = self._resolve_public_key_path()
            result = self.signature_validator.verify_signature(raw_content, signature, key_path)
            if not result.ok:
                raise MagiException(
                    create_plugin_error(
                        ErrorCode.SIGNATURE_VERIFICATION_FAILED,
                        f"Signature verification failed for {path}: {result.reason or 'invalid'} "
                        f"(key={result.key_path or 'fallback'})",
                    )
                )
            LOGGER.info("plugin.signature.verified path=%s key=%s", path, result.key_path or "fallback")
            return

        if digest:
            LOGGER.info(
                "plugin.hash.legacy path=%s note=verify-only deprecation_schedule=6m_grace+3m_warn+3m_removal",
                path,
            )
            result = self.signature_validator.verify_hash(raw_content, digest)
            if not result.ok:
                LOGGER.warning(
                    "plugin.hash.mismatch path=%s expected=%s actual=%s legacy=%s",
                    path,
                    result.expected,
                    result.actual,
                    result.legacy,
                )
            else:
                LOGGER.info("plugin.hash.verified path=%s legacy=%s", path, result.legacy)

    def _resolve_public_key_path(self) -> Optional[Path]:
        """公開鍵パスを優先順位に基づき解決する。"""
        if self.public_key_path:
            return self.public_key_path

        config_path = getattr(self.config, "plugin_public_key_path", None)
        if config_path:
            return Path(config_path)

        env_path = os.environ.get("MAGI_PLUGIN_PUBKEY_PATH")
        if env_path:
            return Path(env_path)

        default_path = Path.cwd() / "plugins" / "public_key.pem"
        if default_path.exists():
            return default_path

        return None

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
