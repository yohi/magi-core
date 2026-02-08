"""
設定管理

MAGIシステムの設定読み込みと管理を行う
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from magi.config.settings import MagiSettings
from magi.errors import ErrorCode, MagiError, MagiException

# 後方互換のために Config エイリアスを提供
Config = MagiSettings


class ValidationResult:
    """バリデーション結果（後方互換向けの簡易オブジェクト）"""

    def __init__(self, is_valid: bool, errors: Optional[List[str]] = None):
        self.is_valid = is_valid
        self.errors = errors or []


class ConfigManager:
    """設定の読み込みと管理

    環境変数・.env・設定ファイルを統合し、MagiSettings として返す。
    """

    def __init__(self):
        """ConfigManagerを初期化"""
        self._config: Optional[MagiSettings] = None

    def load(
        self, config_path: Optional[Path] = None, force_reload: bool = False
    ) -> MagiSettings:
        """設定を読み込む

        Args:
            config_path: 設定ファイルのパス（省略時はデフォルトパスを検索）
            force_reload: キャッシュを無視して再読み込みするかどうか

        Returns:
            MagiSettings: 読み込んだ設定

        Raises:
            MagiException: 設定不足・バリデーション失敗時
        """
        if self._config is not None and not force_reload:
            return self._config

        file_config = self._load_from_file(config_path)
        try:
            settings = MagiSettings(**file_config)
        except ValidationError as exc:  # Pydantic バリデーション失敗
            raise self._convert_validation_error(exc) from exc

        self._config = settings
        return settings

    def dump_masked(self) -> Dict[str, Any]:
        """マスク済み設定を返す（キャッシュが無ければ読み込み）"""
        config = self._config or self.load()
        return config.dump_masked()

    def validate(self, config: MagiSettings) -> ValidationResult:
        """後方互換のための簡易バリデーション

        MagiSettings.model_validate を再利用し、結果を ValidationResult に包む。
        """
        try:
            MagiSettings.model_validate(config.model_dump())
        except ValidationError as exc:
            messages = [err["msg"] for err in exc.errors()]
            return ValidationResult(is_valid=False, errors=messages)
        return ValidationResult(is_valid=True, errors=[])

    def _load_from_file(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """設定ファイルから読み込み"""
        if config_path is None:
            for path in self._get_default_config_paths():
                if path.exists():
                    config_path = path
                    break

        if config_path is None or not config_path.exists():
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:
                    return {}
                return self._normalize_config(data)
        except yaml.YAMLError as exc:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"設定ファイルの読み込みに失敗しました: {exc}",
                    details={"path": str(config_path)},
                )
            ) from exc

    def _get_default_config_paths(self) -> List[Path]:
        """デフォルトの設定ファイルパスを取得"""
        paths = [
            Path.cwd() / "magi.yaml",
            Path.cwd() / "magi.yml",
            Path.home() / ".magi.yaml",
            Path.home() / ".magi.yml",
            Path.home() / ".config" / "magi" / "config.yaml",
            Path.home() / ".config" / "magi" / "config.yml",
        ]
        return paths

    def _normalize_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """設定ファイルの構造を MagiSettings に合わせてフラット化する"""
        if not isinstance(data, dict):
            return {}

        # 未知キーは残して Pydantic の extra=forbid に検出させるためコピーを保持
        result: Dict[str, Any] = dict(data)

        # 後方互換キーのマッピング
        legacy_to_new = {
            "enable_streaming_output": "streaming_enabled",
            "streaming_emit_timeout_seconds": "streaming_emit_timeout",
            "guardrails_timeout_seconds": "guardrails_timeout",
            "guardrails_on_timeout_behavior": "guardrails_on_timeout",
            "guardrails_on_error_policy": "guardrails_on_error",
        }
        for legacy, new in legacy_to_new.items():
            if legacy in data:
                result[new] = data[legacy]
                result.pop(legacy, None)

        # guardrails セクション
        guardrails_cfg = data.get("guardrails")
        if isinstance(guardrails_cfg, dict):
            if "enabled" in guardrails_cfg:
                result["guardrails_enabled"] = guardrails_cfg.get("enabled")
            if "timeout_seconds" in guardrails_cfg:
                result["guardrails_timeout"] = guardrails_cfg.get("timeout_seconds")
            if "on_timeout_behavior" in guardrails_cfg:
                result["guardrails_on_timeout"] = guardrails_cfg.get(
                    "on_timeout_behavior"
                )
            if "on_error_policy" in guardrails_cfg:
                result["guardrails_on_error"] = guardrails_cfg.get("on_error_policy")
            if isinstance(guardrails_cfg.get("providers"), dict):
                result["guardrails_providers"] = guardrails_cfg.get("providers")
            result.pop("guardrails", None)

        # streaming セクション
        streaming_cfg = data.get("streaming")
        if isinstance(streaming_cfg, dict):
            if "enabled" in streaming_cfg:
                result["streaming_enabled"] = streaming_cfg.get("enabled")
            emitter_cfg = streaming_cfg.get("emitter", {})
            if isinstance(emitter_cfg, dict):
                if "queue_size" in emitter_cfg:
                    result["streaming_queue_size"] = emitter_cfg.get("queue_size")
                if "emit_timeout_seconds" in emitter_cfg:
                    result["streaming_emit_timeout"] = emitter_cfg.get(
                        "emit_timeout_seconds"
                    )
                if "overflow_policy" in emitter_cfg:
                    result["streaming_overflow_policy"] = emitter_cfg.get(
                        "overflow_policy"
                    )
            result.pop("streaming", None)

        # plugins セクション
        plugin_cfg = data.get("plugins")
        if isinstance(plugin_cfg, dict):
            if "public_key_path" in plugin_cfg:
                result["plugin_public_key_path"] = plugin_cfg.get("public_key_path")
            result.pop("plugins", None)
        if "plugin_public_key_path" in data:
            result["plugin_public_key_path"] = data.get("plugin_public_key_path")

        return result

    def _convert_validation_error(self, exc: ValidationError) -> MagiException:
        """Pydantic の ValidationError を MagiException に変換"""
        errors = exc.errors()
        # locが空のリストの場合のIndexErrorを回避
        missing_api_key = any(
            (loc := err.get("loc"))
            and isinstance(loc, (list, tuple))
            and loc
            and loc[0] == "api_key"
            for err in errors
        )
        code = (
            ErrorCode.CONFIG_MISSING_API_KEY.value
            if missing_api_key
            else ErrorCode.CONFIG_INVALID_VALUE.value
        )
        message = "; ".join(err.get("msg", "validation error") for err in errors)
        return MagiException(
            MagiError(
                code=code,
                message=message,
                details={"errors": errors},
                recoverable=False,
            )
        )
