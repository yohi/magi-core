"""
プロバイダレジストリとセレクタ
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set, Type

from magi.config.provider import (
    DEFAULT_PROVIDER_ID,
    ProviderConfig,
    ProviderConfigs,
    SUPPORTED_PROVIDERS,
    mask_secret,
)
from magi.errors import ErrorCode, MagiError, MagiException
from magi.llm.providers import AnthropicAdapter, GeminiAdapter, OpenAIAdapter, ProviderAdapter


@dataclass
class ProviderContext:
    """選択済みプロバイダのコンテキスト"""

    provider_id: str
    api_key: str
    model: str
    endpoint: Optional[str] = None
    options: Dict[str, Any] = None
    used_default: bool = False

    def __post_init__(self) -> None:
        if self.options is None:
            self.options = {}

    @property
    def masked_api_key(self) -> str:
        """マスク済みAPIキー"""
        return mask_secret(self.api_key)

    def to_safe_dict(self) -> Dict[str, Any]:
        """鍵をマスクした安全な辞書"""
        return {
            "provider_id": self.provider_id,
            "api_key": self.masked_api_key,
            "model": self.model,
            "endpoint": self.endpoint,
            "options": self.options,
            "used_default": self.used_default,
        }


class ProviderRegistry:
    """サポートプロバイダの登録と検証"""

    def __init__(
        self,
        configs: ProviderConfigs,
        supported_providers: Optional[Iterable[str]] = None,
    ) -> None:
        self._providers = configs.providers
        self.default_provider = configs.default_provider
        self._supported: Set[str] = set(
            p.lower() for p in (supported_providers or SUPPORTED_PROVIDERS)
        )

    def list(self) -> Iterable[str]:
        """利用可能なプロバイダ一覧"""
        return [p for p in self._providers.keys() if p in self._supported]

    def resolve(self, provider_id: str) -> ProviderConfig:
        """プロバイダIDから設定を解決する"""
        normalized = provider_id.lower()
        if normalized not in self._supported:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"Unknown provider '{provider_id}'.",
                    details={"provider": provider_id},
                    recoverable=False,
                )
            )

        config = self._providers.get(normalized)
        if config is None:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message=(
                        f"Unknown provider '{provider_id}' or provider is not configured."
                    ),
                    details={"provider": provider_id},
                    recoverable=False,
                )
            )

        missing_fields = [
            field
            for field in ("api_key", "model")
            if not getattr(config, field) or not str(getattr(config, field)).strip()
        ]
        if missing_fields:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message=f"Provider '{provider_id}' is missing required fields.",
                    details={
                        "provider": provider_id,
                        "missing_fields": missing_fields,
                    },
                    recoverable=False,
                )
            )

        return config


class ProviderSelector:
    """CLI/Config からプロバイダを選択する"""

    def __init__(
        self,
        registry: ProviderRegistry,
        default_provider: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.default_provider = (default_provider or registry.default_provider).lower()

    def select(self, provider_id: Optional[str] = None) -> ProviderContext:
        """プロバイダを選択し、コンテキストを返す"""
        target = (provider_id or self.default_provider or DEFAULT_PROVIDER_ID).lower()
        used_default = provider_id is None

        config = self.registry.resolve(target)
        return ProviderContext(
            provider_id=config.provider_id,
            api_key=config.api_key,
            model=config.model,
            endpoint=config.endpoint,
            options=config.options,
            used_default=used_default,
        )


class ProviderAdapterFactory:
    """ProviderContextに基づいてアダプタを構築するファクトリ"""

    def __init__(
        self,
        adapter_mapping: Optional[Dict[str, Type[ProviderAdapter]]] = None,
    ) -> None:
        self._adapter_mapping: Dict[str, Type[ProviderAdapter]] = adapter_mapping or {
            "anthropic": AnthropicAdapter,
            "openai": OpenAIAdapter,
            "gemini": GeminiAdapter,
        }

    def build(self, context: ProviderContext) -> ProviderAdapter:
        """Contextに対応するアダプタを生成"""
        key = context.provider_id.lower()
        adapter_cls = self._adapter_mapping.get(key)
        if adapter_cls is None:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"Provider '{context.provider_id}' is not supported.",
                    details={"provider": context.provider_id},
                    recoverable=False,
                )
            )
        return adapter_cls(context)
