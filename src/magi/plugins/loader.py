import asyncio
import contextvars
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic.config import ConfigDict

from magi.config.settings import MagiSettings
from magi.errors import ErrorCode, MagiException, create_plugin_error
from magi.models import PersonaType
from magi.plugins.guard import PluginGuard
from magi.plugins.permission_guard import PluginPermissionGuard
from magi.plugins.signature import PluginSignatureValidator

HASH_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
GUARD = PluginGuard()
LOGGER = logging.getLogger(__name__)
_PLUGIN_LOADER_EXECUTOR = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="magi-plugin-loader",
)


class PluginMetadataModel(BaseModel):
    """プラグインメタデータのスキーマ"""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "1.0.0"
    description: str = ""
    signature: Optional[str] = None
    hash: Optional[str] = None

    @field_validator("hash")
    @classmethod
    def validate_hash(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not HASH_PATTERN.match(value):
            raise ValueError("plugin.hash must be sha256:<64hex> format")
        return value

    @model_validator(mode="after")
    def ensure_security_marker(self) -> "PluginMetadataModel":
        if not self.signature and not self.hash:
            raise ValueError("plugin.signature or plugin.hash is required")
        return self


class BridgeConfigModel(BaseModel):
    """プラグインブリッジ設定のスキーマ"""

    model_config = ConfigDict(extra="forbid")

    command: str
    interface: str = Field(pattern="^(stdio|file)$")
    timeout: int = Field(default=30, gt=0)


class PluginModel(BaseModel):
    """プラグイン定義全体のスキーマ"""

    model_config = ConfigDict(extra="forbid")

    plugin: PluginMetadataModel
    bridge: BridgeConfigModel
    agent_overrides: Dict[str, str] = Field(default_factory=dict)

    @field_validator("agent_overrides")
    @classmethod
    def validate_agent_overrides(cls, value: Dict[str, Any]) -> Dict[str, str]:
        if not isinstance(value, dict):
            raise TypeError("agent_overrides must be a dictionary")
        for key, val in value.items():
            if not isinstance(key, str) or not isinstance(val, str):
                raise ValueError("agent_overrides keys and values must be strings")
        return value


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
        permission_guard: Optional[PluginPermissionGuard] = None,
    ) -> None:
        """初期化

        Args:
            public_key_path: 署名検証に用いる公開鍵パス (優先度最高)
            config: Config または同等のオブジェクト。plugin_public_key_path 属性を参照する
            signature_validator: 検証用のバリデータ (テスト差し替え用)
            permission_guard: プロンプト上書き権限チェック用ガード (テスト差し替え用)
        """
        self.public_key_path = public_key_path
        self.config = config
        self.signature_validator = signature_validator or PluginSignatureValidator()
        self.permission_guard = permission_guard or self._build_permission_guard(config)

    async def load_async(self, path: Path, *, timeout: Optional[float] = None) -> Plugin:
        """プラグインを非同期でロードする"""
        effective_timeout = self._get_load_timeout(timeout)
        start = time.monotonic()
        LOGGER.info("plugin.load.started path=%s timeout=%.3f", path, effective_timeout)
        try:
            plugin = await asyncio.wait_for(self._load_async_impl(path), timeout=effective_timeout)
        except asyncio.TimeoutError as e:
            duration = time.monotonic() - start
            LOGGER.error(
                "plugin.load.timeout path=%s effective_timeout=%.3f duration=%.3f",
                path,
                effective_timeout,
                duration,
                exc_info=True,
            )
            raise MagiException(
                create_plugin_error(
                    ErrorCode.PLUGIN_LOAD_TIMEOUT,
                    f"Plugin load timed out for {path} after {effective_timeout:.3f}s",
                )
            ) from e
        except Exception:
            LOGGER.exception("plugin.load.failed path=%s", path)
            raise
        duration = time.monotonic() - start
        LOGGER.info("plugin.load.completed path=%s duration=%.3f", path, duration)
        return plugin

    async def load_all_async(
        self,
        paths: List[Path],
        *,
        timeout: Optional[float] = None,
        concurrency_limit: Optional[int] = None,
    ) -> List[Union[Plugin, Exception]]:
        """複数プラグインを非同期でロードする

        Args:
            paths: ロードするプラグインファイルのパスリスト
            timeout: 各プラグインのロードタイムアウト(秒)
            concurrency_limit: 同時実行数の制限。None の場合は設定値を使用。

        Returns:
            プラグインまたは例外のリスト。各要素は成功時はPluginオブジェクト、
            失敗時はExceptionオブジェクト。1つのプラグインの失敗が他のプラグインの
            ロードを妨げることはない。
        """
        effective_limit = self._get_concurrency_limit(concurrency_limit)
        semaphore = asyncio.Semaphore(effective_limit)

        async def _load_with_limit(path: Path) -> Plugin:
            wait_started_at: Optional[float] = None
            if semaphore.locked():
                wait_started_at = time.monotonic()
                LOGGER.info(
                    "plugin.load.wait_start path=%s limit=%d",
                    path,
                    effective_limit,
                )

            await semaphore.acquire()
            if wait_started_at is not None:
                wait_duration = time.monotonic() - wait_started_at
                LOGGER.info(
                    "plugin.load.wait_end path=%s limit=%d wait_duration=%.3f",
                    path,
                    effective_limit,
                    wait_duration,
                )

            try:
                return await self.load_async(path, timeout=timeout)
            finally:
                semaphore.release()

        tasks = [_load_with_limit(path) for path in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _run_in_executor(self, func, /, *args, **kwargs):
        loop = asyncio.get_running_loop()
        context = contextvars.copy_context()
        return await loop.run_in_executor(
            _PLUGIN_LOADER_EXECUTOR,
            lambda: context.run(func, *args, **kwargs),
        )

    async def _load_async_impl(self, path: Path) -> Plugin:
        """load の非同期版実装"""
        if not path.exists():
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                f"Plugin file not found: {path}"
            ))

        try:
            content = await self._run_in_executor(path.read_text, encoding="utf-8")
            plugin_data = self._parse_yaml(content)
        except Exception as e:
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                f"Failed to parse plugin YAML from {path}: {e}"
            )) from e

        plugin_model = self._validate_or_raise(plugin_data, path)

        await self._verify_security_async(content, plugin_model.model_dump(), path)

        return self._build_plugin(plugin_model)

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

        plugin_model = self._validate_or_raise(plugin_data, path)

        self._verify_security(content, plugin_model.model_dump(), path)

        return self._build_plugin(plugin_model)

    def validate(self, plugin_data: Dict) -> "ValidationResult":
        """プラグイン定義の妥当性を検証"""
        errors: List[str] = []
        try:
            plugin_model = PluginModel.model_validate(plugin_data)
        except ValidationError as exc:
            errors.extend(self._format_pydantic_errors(exc))
            return ValidationResult(is_valid=False, errors=errors)

        try:
            GUARD.validate(plugin_model.bridge.command, [])
        except MagiException as exc:
            errors.append(exc.error.message)

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
            if self._is_production_mode() and key_path is None:
                raise MagiException(
                    create_plugin_error(
                        ErrorCode.SIGNATURE_VERIFICATION_FAILED,
                        (
                            "Production mode requires explicit plugin public key path "
                            "(production_mode=True). Set plugin_public_key_path or "
                            "MAGI_PLUGIN_PUBKEY_PATH."
                        ),
                    )
                )
            result = self.signature_validator.verify_signature(raw_content, signature, key_path)
            if not result.ok:
                LOGGER.warning(
                    "plugin.load.signature_failed path=%s reason=%s",
                    path,
                    result.reason or "invalid",
                )
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

    async def _verify_security_async(self, raw_content: str, plugin_data: Dict[str, Any], path: Path) -> None:
        """署名/ハッシュ検証を非同期で実施する。"""
        await self._run_in_executor(self._verify_security, raw_content, plugin_data, path)

    def _is_production_mode(self) -> bool:
        """本番運用モードかどうかを返す"""
        return bool(getattr(self.config, "production_mode", False))

    def _resolve_public_key_path(self) -> Optional[Path]:
        """公開鍵パスを優先順位に基づき解決する。"""
        production_mode = self._is_production_mode()

        def _log_resolution(source: str, resolved: Optional[Path]) -> Optional[Path]:
            LOGGER.info(
                "plugin.signature.key_path_resolved source=%s path=%s production_mode=%s",
                source,
                resolved,
                production_mode,
            )
            return resolved

        if self.public_key_path:
            return _log_resolution("init_arg", Path(self.public_key_path))

        config_path = getattr(self.config, "plugin_public_key_path", None)
        if config_path:
            return _log_resolution("config", Path(config_path))

        env_path = os.environ.get("MAGI_PLUGIN_PUBKEY_PATH")
        if env_path:
            return _log_resolution("env", Path(env_path))

        default_path = Path.cwd() / "plugins" / "public_key.pem"
        if production_mode:
            if default_path.exists():
                LOGGER.warning(
                    "plugin.signature.key_path_ignored source=cwd_default path=%s production_mode=True",
                    default_path,
                )
            LOGGER.error(
                "plugin.signature.key_path_missing production_mode=True "
                "hint=set plugin_public_key_path or MAGI_PLUGIN_PUBKEY_PATH"
            )
            return None

        if default_path.exists():
            return _log_resolution("cwd_default", default_path)

        LOGGER.warning(
            "plugin.signature.key_path_missing production_mode=%s",
            production_mode,
        )
        return None

    def _validate_or_raise(self, plugin_data: Dict[str, Any], path: Path) -> PluginModel:
        """Pydantic 検証を行い、失敗時は MagiException を送出する。"""
        try:
            plugin_model = PluginModel.model_validate(plugin_data)
        except ValidationError as exc:
            errors = self._format_pydantic_errors(exc)
            raise MagiException(
                create_plugin_error(
                    ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                    f"Plugin validation failed for {path}: {', '.join(errors)}",
                )
            ) from exc

        try:
            GUARD.validate(plugin_model.bridge.command, [])
        except MagiException as exc:
            raise MagiException(
                create_plugin_error(
                    ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                    f"Plugin validation failed for {path}: {exc.error.message}",
                )
            ) from exc

        return plugin_model

    def _get_load_timeout(self, timeout: Optional[float]) -> float:
        """ロードタイムアウトを解決する"""
        if timeout is not None:
            return float(timeout)

        config_timeout = None
        if self.config is not None:
            config_timeout = getattr(self.config, "plugin_load_timeout", None)

        base_timeout = float(config_timeout) if config_timeout is not None else 30.0
        return max(base_timeout, 0.02)

    def _get_concurrency_limit(self, concurrency_limit: Optional[int]) -> int:
        """プラグインロードの同時実行上限を解決する"""
        if concurrency_limit is not None and concurrency_limit > 0:
            return int(concurrency_limit)

        config_limit = None
        if self.config is not None:
            config_limit = getattr(self.config, "plugin_concurrency_limit", None)

        if isinstance(config_limit, int) and config_limit > 0:
            return config_limit

        return 3

    @staticmethod
    def _format_pydantic_errors(exc: ValidationError) -> List[str]:
        """Pydantic のエラーを人間可読な文字列に整形する"""
        formatted = []
        for err in exc.errors():
            section_error = PluginLoader._describe_section_error(err)
            if section_error:
                formatted.append(section_error)
                continue
            loc = ".".join(str(part) for part in err.get("loc", []))
            msg = err.get("msg", "validation error")
            formatted.append(f"{loc}: {msg}" if loc else msg)
        return formatted

    @staticmethod
    def _describe_section_error(err: Dict[str, Any]) -> Optional[str]:
        """plugin/bridge セクション欠落時のメッセージを明示する"""
        loc = err.get("loc", [])
        if len(loc) != 1:
            return None
        section = loc[0]
        if section not in ("plugin", "bridge"):
            return None

        err_type = err.get("type") or ""
        msg = err.get("msg") or ""
        if err_type == "missing" or err_type.endswith("_type") or "valid dictionary" in msg:
            return f"Missing or invalid '{section}' section"
        return None

    def _build_plugin(self, plugin_model: PluginModel) -> Plugin:
        """検証済みのモデルからPluginオブジェクトを構築する"""
        metadata = PluginMetadata(
            name=plugin_model.plugin.name,
            version=plugin_model.plugin.version,
            description=plugin_model.plugin.description,
            signature=plugin_model.plugin.signature,
            hash=plugin_model.plugin.hash,
        )
        bridge = BridgeConfig(
            command=plugin_model.bridge.command,
            interface=plugin_model.bridge.interface,
            timeout=plugin_model.bridge.timeout,
        )

        filtered_overrides = plugin_model.agent_overrides
        if self.permission_guard is not None:
            check_result = self.permission_guard.check_override_permission(
                metadata,
                plugin_model.agent_overrides,
            )
            filtered_overrides = check_result.filtered_overrides

        agent_overrides: Dict[PersonaType, str] = {}
        for persona_name, override_prompt in filtered_overrides.items():
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

    @staticmethod
    def _build_permission_guard(config: Optional[Any]) -> Optional[PluginPermissionGuard]:
        """設定から PluginPermissionGuard を初期化する。"""
        if isinstance(config, MagiSettings):
            return PluginPermissionGuard(config)
        return None

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
