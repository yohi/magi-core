"""
プロバイダ設定の読み込みと管理
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from magi.errors import ErrorCode, MagiError, MagiException

# デフォルトおよびサポートするプロバイダ
DEFAULT_PROVIDER_ID = "anthropic"
SUPPORTED_PROVIDERS = (
    "anthropic",
    "openai",
    "gemini",
    "claude",
    "copilot",
    "antigravity",
)
AUTH_BASED_PROVIDERS = ("claude", "copilot", "antigravity")
RECOMMENDED_MODELS = {
    "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    "openai": ["gpt-4o", "gpt-4-turbo"],
    "gemini": ["gemini-2.0-flash", "gemini-2.0-flash-exp"],
    "antigravity": ["gemini-2.0-flash-exp"],
    "claude": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    "copilot": ["gpt-4o", "gpt-4"],
}

logger = logging.getLogger(__name__)


def mask_secret(value: str) -> str:
    """鍵やトークンをマスクしてログ出力を避ける"""
    if not value:
        return "***"
    if len(value) <= 4:
        return "*" * len(value)
    return f"***{value[-4:]}"


@dataclass
class ProviderConfig:
    """プロバイダ個別設定"""

    provider_id: str
    api_key: str = ""
    model: str = ""
    endpoint: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)

    @property
    def masked_api_key(self) -> str:
        """マスク済みAPIキー"""
        return mask_secret(self.api_key)

    def masked_dict(self) -> Dict[str, Any]:
        """鍵をマスクした安全な辞書"""
        return {
            "provider_id": self.provider_id,
            "api_key": self.masked_api_key,
            "model": self.model,
            "endpoint": self.endpoint,
            "options": self._masked_options(),
        }

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(provider_id={self.provider_id}, "
            f"api_key={self.masked_api_key}, model={self.model}, "
            f"endpoint={self.endpoint}, options=<redacted>)"
        )

    def _masked_options(self) -> Dict[str, Any]:
        """options 内の値をマスクした辞書"""
        masked: Dict[str, Any] = {}
        for key, value in self.options.items():
            if isinstance(value, str):
                masked[key] = mask_secret(value)
            else:
                masked[key] = value
        return masked


@dataclass
class ProviderConfigs:
    """プロバイダ設定集合"""

    providers: Dict[str, ProviderConfig]
    default_provider: str = DEFAULT_PROVIDER_ID


class ProviderConfigLoader:
    """プロバイダ設定ローダー(env/yaml + キャッシュ + バリデーション)"""

    def __init__(self) -> None:
        self._cache: Optional[ProviderConfigs] = None
        self._cache_validated: bool = False

    def load(
        self,
        config_path: Optional[Path] = None,
        force_reload: bool = False,
        skip_validation: bool = False,
    ) -> ProviderConfigs:
        """プロバイダ設定を読み込む"""
        if self._cache is not None and not force_reload:
            if skip_validation or self._cache_validated:
                return self._cache

        file_providers, file_default = self._load_from_file(config_path)
        env_providers, env_default = self._load_from_env()
        merged = self._merge_providers(file_providers, env_providers)
        default_provider = self._resolve_default_provider(file_default, env_default)
        if not skip_validation:
            self._validate(merged, default_provider)

        self._cache = ProviderConfigs(
            providers=merged,
            default_provider=default_provider,
        )
        self._cache_validated = not skip_validation
        return self._cache

    def _load_from_file(
        self,
        config_path: Optional[Path],
    ) -> Tuple[Dict[str, ProviderConfig], Optional[str]]:
        """設定ファイルからプロバイダ設定を読み込む"""
        resolved_path = config_path or self._find_default_config()
        if resolved_path is None or not resolved_path.exists():
            return {}, None

        try:
            with resolved_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as e:
            logger.error(
                "Failed to load provider config file: path=%s error=%s",
                resolved_path,
                e,
                exc_info=True,
            )
            return {}, None

        if not isinstance(data, dict):
            logger.error(
                "Invalid provider config structure: expected mapping but got %s at %s",
                type(data).__name__,
                resolved_path,
            )
            return {}, None

        providers: Dict[str, ProviderConfig] = {}
        raw_providers = data.get("providers")
        if isinstance(raw_providers, dict):
            for pid, cfg in raw_providers.items():
                if not isinstance(cfg, dict):
                    continue
                provider_id = str(pid).lower()
                providers[provider_id] = self._build_provider_config(
                    provider_id=provider_id,
                    cfg=cfg,
                )

        # 既存の単一プロバイダ設定をデフォルトとして扱う
        if DEFAULT_PROVIDER_ID not in providers:
            legacy_key = data.get("api_key")
            legacy_model = data.get("model")
            if legacy_key or legacy_model:
                providers[DEFAULT_PROVIDER_ID] = ProviderConfig(
                    provider_id=DEFAULT_PROVIDER_ID,
                    api_key=str(legacy_key or ""),
                    model=str(legacy_model or ""),
                )

        default_provider = None
        raw_default = data.get("default_provider")
        if isinstance(raw_default, str):
            default_provider = raw_default.lower()

        return providers, default_provider

    def _load_from_env(self) -> Tuple[Dict[str, ProviderConfig], Optional[str]]:
        """環境変数からプロバイダ設定を読み込む"""
        providers: Dict[str, ProviderConfig] = {}

        for provider_id in SUPPORTED_PROVIDERS:
            prefix = f"MAGI_{provider_id.upper()}_"
            api_key = os.environ.get(f"{prefix}API_KEY", "")
            model = os.environ.get(f"{prefix}MODEL", "")
            endpoint = os.environ.get(f"{prefix}ENDPOINT")
            options_raw = os.environ.get(f"{prefix}OPTIONS")
            options = self._parse_options(options_raw)

            if api_key or model or endpoint or options:
                providers[provider_id] = ProviderConfig(
                    provider_id=provider_id,
                    api_key=api_key,
                    model=model,
                    endpoint=endpoint,
                    options=options,
                )

        # 既存の単一プロバイダ環境変数をAnthropic扱いで読み込む
        if DEFAULT_PROVIDER_ID not in providers:
            legacy_key = os.environ.get("MAGI_API_KEY", "")
            legacy_model = os.environ.get("MAGI_MODEL", "")
            if legacy_key or legacy_model:
                providers[DEFAULT_PROVIDER_ID] = ProviderConfig(
                    provider_id=DEFAULT_PROVIDER_ID,
                    api_key=legacy_key,
                    model=legacy_model,
                )

        env_default = os.environ.get("MAGI_DEFAULT_PROVIDER")
        if isinstance(env_default, str):
            env_default = env_default.strip().lower() or None

        return providers, env_default

    def _merge_providers(
        self,
        file_providers: Dict[str, ProviderConfig],
        env_providers: Dict[str, ProviderConfig],
    ) -> Dict[str, ProviderConfig]:
        """ファイル設定に環境変数を上書きマージする"""
        merged: Dict[str, ProviderConfig] = dict(file_providers)

        for provider_id, env_cfg in env_providers.items():
            base = merged.get(provider_id)
            if base:
                merged[provider_id] = ProviderConfig(
                    provider_id=provider_id,
                    api_key=env_cfg.api_key or base.api_key,
                    model=env_cfg.model or base.model,
                    endpoint=env_cfg.endpoint or base.endpoint,
                    options=env_cfg.options or base.options,
                )
            else:
                merged[provider_id] = env_cfg

        return merged

    def _resolve_default_provider(
        self,
        config_default: Optional[str],
        env_default: Optional[str],
    ) -> str:
        """デフォルトプロバイダを解決する（config > env > built-in を担当）

        CLIフラグによる上書きは CLI 層で行われるため、本メソッドは
        設定ファイル・環境変数・ビルトイン既定の優先度のみを扱う。
        """
        if config_default:
            return config_default
        if env_default:
            return env_default
        return DEFAULT_PROVIDER_ID

    def _validate(
        self,
        providers: Dict[str, ProviderConfig],
        default_provider: str,
    ) -> None:
        """必須フィールドとデフォルト設定の検証"""
        if not providers:
            message = "プロバイダ設定が存在しません。少なくともデフォルトプロバイダを設定してください。"
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message=message,
                    details={
                        "providers": {},
                        "missing_fields": {"default_provider": ["api_key", "model"]},
                        "expected_default": default_provider,
                    },
                    recoverable=False,
                )
            )

        errors = []
        for provider_id, cfg in providers.items():
            required_fields = ["model"]
            if provider_id not in AUTH_BASED_PROVIDERS:
                required_fields.insert(0, "api_key")
            missing_fields = [
                field
                for field in required_fields
                if not getattr(cfg, field) or not str(getattr(cfg, field)).strip()
            ]
            if missing_fields:
                errors.append(
                    {
                        "provider": provider_id,
                        "missing_fields": missing_fields,
                    }
                )

        if errors:
            providers_with_error = ", ".join([e["provider"] for e in errors])
            aggregated_missing = {
                entry["provider"]: entry["missing_fields"] for entry in errors
            }
            # 認証ベースのプロバイダの場合は、認証前は設定が不足していても許容したい場合があるが、
            # 現状は一律エラーにしている。
            # ただし、デフォルトプロバイダが設定済みであれば、他のプロバイダの設定不足は無視すべきかもしれない。
            # ここでは厳密なチェックを維持しつつ、呼び出し側でハンドリングすることを想定。
            message = f"プロバイダ設定が不足しています: {providers_with_error}"
            detail = {
                "providers": errors,
                "missing_fields": aggregated_missing,
            }
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message=message,
                    details=detail,
                    recoverable=False,
                )
            )

        if default_provider not in providers:
            message = (
                f"デフォルトプロバイダ '{default_provider}' の設定が見つかりません。"
            )
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message=message,
                    details={
                        "default_provider": default_provider,
                        "available_providers": list(providers.keys()),
                    },
                    recoverable=False,
                )
            )

    def _build_provider_config(
        self,
        provider_id: str,
        cfg: Dict[str, Any],
    ) -> ProviderConfig:
        """辞書から ProviderConfig を構築"""
        options = cfg.get("options") if isinstance(cfg, dict) else {}
        options = options if isinstance(options, dict) else {}
        return ProviderConfig(
            provider_id=provider_id,
            api_key=str(cfg.get("api_key") or ""),
            model=str(cfg.get("model") or ""),
            endpoint=cfg.get("endpoint"),
            options=options,
        )

    def _find_default_config(self) -> Optional[Path]:
        """デフォルトの設定ファイルパスを探索"""
        paths = [
            Path.cwd() / "magi.yaml",
            Path.cwd() / "magi.yml",
            Path.home() / ".magi.yaml",
            Path.home() / ".magi.yml",
            Path.home() / ".config" / "magi" / "config.yaml",
            Path.home() / ".config" / "magi" / "config.yml",
        ]
        for path in paths:
            if path.exists():
                return path
        return None

    def _parse_options(self, raw: Optional[str]) -> Dict[str, Any]:
        """オプション文字列(JSON)を辞書に変換"""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            snippet = raw if len(raw) <= 200 else f"{raw[:200]}...<truncated>"
            logger.error(
                "Failed to parse provider options JSON: raw=%s error=%s",
                snippet,
                e,
                exc_info=True,
            )
            return {}

        if not isinstance(parsed, dict):
            logger.warning(
                "Provider options is not a JSON object: type=%s value=%s",
                type(parsed).__name__,
                parsed,
            )
            return {}

        return parsed
