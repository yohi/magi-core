import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from magi.errors import create_plugin_error, ErrorCode, MagiException
from magi.models import PersonaType 

@dataclass
class PluginMetadata:
    name: str
    version: str = "1.0.0"
    description: str = ""

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

class PluginLoader:
    """YAMLプラグイン定義の読み込みとバリデーション"""
    
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

        metadata = PluginMetadata(
            name=plugin_data["plugin"]["name"],
            version=plugin_data["plugin"].get("version", "1.0.0"),
            description=plugin_data["plugin"].get("description", "")
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
        
        return Plugin(metadata=metadata, bridge=bridge, agent_overrides=agent_overrides)

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

        # Validate 'bridge' section
        if "bridge" not in plugin_data or not isinstance(plugin_data["bridge"], dict):
            errors.append("Missing or invalid 'bridge' section.")
        else:
            if "command" not in plugin_data["bridge"] or not isinstance(plugin_data["bridge"]["command"], str):
                errors.append("Bridge 'command' is required and must be a string.")
            if "interface" not in plugin_data["bridge"] or plugin_data["bridge"]["interface"] not in ["stdio", "file"]:
                errors.append("Bridge 'interface' is required and must be 'stdio' or 'file'.")
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
                        errors.append(f"Invalid persona name in agent_overrides: {persona_name}. Must be MELCHIOR, BALTHASAR, or CASPER.")


        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _parse_yaml(self, content: str) -> Dict:
        """YAML文字列をパース"""
        return yaml.safe_load(content)

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
