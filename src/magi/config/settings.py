"""Pydantic V2 ベースの統合設定モデル"""

import logging
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class MagiSettings(BaseSettings):
    """MAGI System の統合設定"""

    model_config = SettingsConfigDict(
        env_prefix="MAGI_",
        env_file=".env",
        extra="forbid",
    )

    def __init__(self, **data: Any):
        data = self._apply_legacy_keys(data)
        super().__init__(**data)

    # API 設定
    api_key: str = Field(..., description="Anthropic API Key")
    model: str = Field(default="claude-sonnet-4-20250514")
    timeout: int = Field(default=60, ge=1)
    retry_count: int = Field(default=3, ge=0, le=10)

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
        return (
            env_settings,
            dotenv_settings,
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
        return coerced

    def dump_masked(self) -> dict:
        """機微情報をマスクした設定を返却する"""
        data = self.model_dump()
        api_key = data.get("api_key")
        if api_key:
            data["api_key"] = (
                f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
            )
        return data

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
    def guardrails_on_timeout_behavior(self, value: Literal["fail-open", "fail-closed"]) -> None:
        if value not in ("fail-open", "fail-closed"):
            raise ValueError(
                f"guardrails_on_timeout_behavior must be 'fail-open' or 'fail-closed', got: {value}"
            )
        self.guardrails_on_timeout = value

    @property
    def guardrails_on_error_policy(self) -> str:
        return self.guardrails_on_error

    @guardrails_on_error_policy.setter
    def guardrails_on_error_policy(self, value: Literal["fail-open", "fail-closed"]) -> None:
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
