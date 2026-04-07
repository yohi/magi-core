"""Pydantic V2 ベースの統合設定モデル"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class LLMConfig(BaseModel):
    """LLMプロバイダ設定"""

    model: Optional[str] = None
    api_key: Optional[str] = None
    timeout: Optional[int] = None
    retry_count: Optional[int] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=1.0)


class PersonaConfig(BaseModel):
    """ペルソナ個別設定"""

    llm: Optional[LLMConfig] = None


class MagiSettings(BaseSettings):
    """MAGI System の統合設定"""

    model_config = SettingsConfigDict(
        env_prefix="MAGI_",
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="forbid",
        populate_by_name=True,
    )

    def __init__(self, **data: Any):
        data = self._apply_legacy_keys(data)
        super().__init__(**data)

    # API 設定
    api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "MAGI_ANTHROPIC_API_KEY", "MAGI_API_KEY", "api_key"
        ),
    )
    model: str = Field(default="claude-3-5-sonnet-20241022")
    timeout: int = Field(default=60, ge=1)
    retry_count: int = Field(default=3, ge=0, le=10)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)

    # ペルソナ設定
    personas: Dict[str, PersonaConfig] = Field(default_factory=dict)

    # プロバイダ設定
    providers: Optional[Dict[str, Any]] = Field(default_factory=dict)
    default_provider: Optional[str] = None

    # 合議設定
    debate_rounds: int = Field(default=1, ge=1)
    voting_threshold: Literal["majority", "unanimous"] = "majority"
    quorum_threshold: int = Field(default=2, ge=1, le=3)
    token_budget: int = Field(default=8192, ge=1)
    schema_retry_count: int = Field(default=3, ge=0, le=10)
    template_ttl_seconds: int = Field(default=300, ge=1)
    vote_template_name: str = Field(default="vote_prompt")
    template_base_path: str = Field(default="templates")

    # 並行処理設定
    llm_concurrency_limit: int = Field(default=5, ge=1, le=20)
    plugin_concurrency_limit: int = Field(default=3, ge=1, le=10)
    plugin_load_timeout: float = Field(default=30.0, gt=0)

    # ストリーミング設定
    streaming_enabled: bool = False
    streaming_queue_size: int = Field(default=100, ge=1)
    streaming_overflow_policy: Literal["drop", "backpressure"] = "drop"
    streaming_emit_timeout: float = Field(default=2.0, gt=0)
    stream_retry_count: int = Field(default=5, ge=0)

    # Guardrails 設定
    guardrails_enabled: bool = False
    guardrails_timeout: float = Field(default=3.0, gt=0)
    guardrails_on_timeout: Literal["fail-open", "fail-closed"] = "fail-closed"
    guardrails_on_error: Literal["fail-open", "fail-closed"] = "fail-closed"
    guardrails_providers: Dict[str, Any] = Field(default_factory=dict)

    # ハードニング設定
    log_context_reduction_key: bool = True
    enable_hardened_consensus: bool = True
    legacy_fallback_on_fail_safe: bool = False

    # プラグイン権限設定
    plugin_prompt_override_allowed: bool = False
    plugin_trusted_signatures: list[str] = Field(default_factory=list)

    # 本番運用モード
    production_mode: bool = False
    plugin_public_key_path: Optional[Path] = None

    # 出力設定
    output_format: Literal["json", "markdown"] = "markdown"

    # WebUI 設定 (from .env/env)
    max_concurrency: int = Field(
        default=10,
        ge=1,
        validation_alias=AliasChoices("MAX_CONCURRENCY", "max_concurrency"),
    )
    session_ttl_sec: int = Field(
        default=600,
        ge=1,
        validation_alias=AliasChoices("SESSION_TTL_SEC", "session_ttl_sec"),
    )
    cors_origins: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins")
    )
    vite_api_base: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("VITE_API_BASE", "vite_api_base")
    )
    vite_ws_base: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("VITE_WS_BASE", "vite_ws_base")
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ) -> Tuple[Any, ...]:
        """設定ソースの優先順位をカスタマイズ（env > dotenv > init）"""
        allowed_fields = set(cls.model_fields)

        def _filtered(source):
            def _inner():
                data = source()
                filtered = {}
                for key, value in data.items():
                    if key not in allowed_fields:
                        continue
                    if value is None:
                        continue
                    if isinstance(value, str) and value == "":
                        continue
                    filtered[key] = value
                return filtered

            return _inner

        return (
            _filtered(env_settings),
            _filtered(dotenv_settings),
            init_settings,
            file_secret_settings,
        )

    @field_validator("plugin_public_key_path")
    @classmethod
    def validate_production_key_path(
        cls,
        value: Optional[Path],
        info: ValidationInfo,
    ) -> Optional[Path]:
        """production_mode 時は公開鍵パスを必須化"""
        if info.data.get("production_mode") and value is None:
            raise ValueError(
                "production_mode=True では plugin_public_key_path の明示指定が必須です"
            )
        return value

    @classmethod
    def _apply_legacy_keys(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """後方互換のために旧フィールド名を新フィールドに移し替える"""
        mapping = {
            "enable_streaming_output": "streaming_enabled",
            "streaming_emit_timeout_seconds": "streaming_emit_timeout",
            "enable_guardrails": "guardrails_enabled",
            "guardrails_timeout_seconds": "guardrails_timeout",
            "guardrails_on_timeout_behavior": "guardrails_on_timeout",
            "guardrails_on_error_policy": "guardrails_on_error",
        }
        coerced = dict(data)

        # 指摘事項: 呼び出し元の辞書を壊さないよう、ネストされた辞書も明示的にコピーする
        if "providers" in coerced and isinstance(coerced["providers"], dict):
            coerced["providers"] = dict(coerced["providers"])
            if "anthropic" in coerced["providers"] and isinstance(
                coerced["providers"]["anthropic"], dict
            ):
                coerced["providers"]["anthropic"] = dict(coerced["providers"]["anthropic"])

        for legacy, new in mapping.items():
            if legacy in coerced:
                if new not in coerced:
                    # 新しいキーが存在しない場合のみ、レガシーキーを移動
                    coerced[new] = coerced.pop(legacy)
                else:
                    # 両方のキーが存在する場合、新しいキーを優先
                    coerced.pop(legacy)
                    logger.warning(
                        f"両方のキーが設定に存在します: レガシーキー '{legacy}' と新しいキー '{new}'。"
                        f"新しいキー '{new}' を優先し、レガシーキー '{legacy}' は無視されます。"
                    )

        # MAGI_ANTHROPIC_API_KEY を providers["anthropic"]["api_key"] にマッピング
        # 環境変数を最優先する
        env_api_key = os.environ.get("MAGI_ANTHROPIC_API_KEY") or os.environ.get(
            "MAGI_API_KEY"
        )
        api_key = env_api_key or coerced.get("api_key")

        # プロバイダ設定の正規化（キーが存在し、辞書でない場合のみ）
        if "providers" in coerced and not isinstance(coerced["providers"], dict):
            coerced["providers"] = {}
        if (
            "providers" in coerced
            and isinstance(coerced["providers"], dict)
            and "anthropic" in coerced["providers"]
            and not isinstance(coerced["providers"]["anthropic"], dict)
        ):
            coerced["providers"]["anthropic"] = {}

        if api_key:
            coerced["api_key"] = api_key
            # api_key 同期のために必要な階層を作成
            if "providers" not in coerced:
                coerced["providers"] = {}
            if "anthropic" not in coerced["providers"]:
                coerced["providers"]["anthropic"] = {}

            # 指摘事項: 上位プライオリティが勝つよう、常に同期する
            coerced["providers"]["anthropic"]["api_key"] = api_key

        return coerced

    def dump_masked(self) -> dict:
        """機微情報をマスクした設定を返却する"""
        data = self.model_dump()

        # トップレベルの api_key を削除（テストの期待値に合わせる）
        data.pop("api_key", None)

        def _mask(val: str) -> str:
            return f"{val[:8]}...{val[-4:]}" if len(val) > 12 else "***"

        # 各プロバイダの設定は providers 辞書内にあるため、
        # 必要に応じてそこでマスク処理が行われることを期待するか、
        # ここで providers 内の api_key を一括マスクする。
        if "providers" in data and isinstance(data["providers"], dict):
            for p_cfg in data["providers"].values():
                if isinstance(p_cfg, dict):
                    # api_key のマスク
                    val = p_cfg.get("api_key")
                    if val:
                        p_cfg["api_key"] = _mask(val)

                    # 指摘事項: options 内のトークン/ヘッダもマスクする
                    options = p_cfg.get("options")
                    if isinstance(options, dict):
                        for k, v in options.items():
                            if isinstance(v, str):
                                options[k] = _mask(v)

        # 各ペルソナの LLM 設定をマスク
        if "personas" in data and isinstance(data["personas"], dict):
            for p_cfg in data["personas"].values():
                if isinstance(p_cfg, dict) and "llm" in p_cfg:
                    llm_cfg = p_cfg["llm"]
                    if isinstance(llm_cfg, dict):
                        val = llm_cfg.get("api_key")
                        if val:
                            llm_cfg["api_key"] = _mask(val)
        return data

    @model_validator(mode="after")
    def _sync_api_key_to_providers(self) -> "MagiSettings":
        """トップレベルの api_key を providers['anthropic'] に同期する（双方向）"""
        # 1. 逆方向同期: providers['anthropic']['api_key'] があり、api_key が空の場合
        if not self.api_key and isinstance(self.providers, dict):
            anthropic_cfg = self.providers.get("anthropic")
            if isinstance(anthropic_cfg, dict):
                p_api_key = anthropic_cfg.get("api_key")
                if p_api_key:
                    self.api_key = p_api_key

        # 2. 順方向同期: api_key がある場合
        if self.api_key:
            if not isinstance(self.providers, dict):
                self.providers = {}
            if "anthropic" not in self.providers or not isinstance(
                self.providers["anthropic"], dict
            ):
                self.providers["anthropic"] = {}

            # 指摘事項: 常に同期して乖離を防ぐ
            self.providers["anthropic"]["api_key"] = self.api_key
        return self

    # 互換性プロパティ（既存コードを壊さないためのエイリアス）
    @property
    def enable_streaming_output(self) -> bool:
        return self.streaming_enabled

    @enable_streaming_output.setter
    def enable_streaming_output(self, value: bool) -> None:
        self.streaming_enabled = value

    @property
    def streaming_emit_timeout_seconds(self) -> float:
        return self.streaming_emit_timeout

    @streaming_emit_timeout_seconds.setter
    def streaming_emit_timeout_seconds(self, value: float) -> None:
        self.streaming_emit_timeout = value

    @property
    def guardrails_timeout_seconds(self) -> float:
        return self.guardrails_timeout

    @guardrails_timeout_seconds.setter
    def guardrails_timeout_seconds(self, value: float) -> None:
        self.guardrails_timeout = value

    @property
    def guardrails_on_timeout_behavior(self) -> str:
        return self.guardrails_on_timeout

    @guardrails_on_timeout_behavior.setter
    def guardrails_on_timeout_behavior(
        self, value: Literal["fail-open", "fail-closed"]
    ) -> None:
        if value not in ("fail-open", "fail-closed"):
            raise ValueError(
                f"guardrails_on_timeout_behavior must be 'fail-open' or 'fail-closed', got: {value}"
            )
        self.guardrails_on_timeout = value

    @property
    def guardrails_on_error_policy(self) -> str:
        return self.guardrails_on_error

    @guardrails_on_error_policy.setter
    def guardrails_on_error_policy(
        self, value: Literal["fail-open", "fail-closed"]
    ) -> None:
        if value not in ("fail-open", "fail-closed"):
            raise ValueError(
                f"guardrails_on_error_policy must be 'fail-open' or 'fail-closed', got: {value}"
            )
        self.guardrails_on_error = value

    @property
    def enable_guardrails(self) -> bool:
        return self.guardrails_enabled

    @enable_guardrails.setter
    def enable_guardrails(self, value: bool) -> None:
        self.guardrails_enabled = value
