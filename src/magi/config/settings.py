"""Pydantic V2 ベースの統合設定モデル"""

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, FieldValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MagiSettings(BaseSettings):
    """MAGI System の統合設定"""

    model_config = SettingsConfigDict(
        env_prefix="MAGI_",
        env_file=".env",
        extra="forbid",
    )

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

    # 並行処理設定
    llm_concurrency_limit: int = Field(default=5, ge=1, le=20)
    plugin_concurrency_limit: int = Field(default=3, ge=1, le=10)
    plugin_load_timeout: float = Field(default=30.0, gt=0)

    # ストリーミング設定
    streaming_enabled: bool = False
    streaming_queue_size: int = Field(default=100, ge=1)
    streaming_overflow_policy: Literal["drop", "backpressure"] = "drop"
    streaming_emit_timeout: float = Field(default=2.0, gt=0)

    # Guardrails 設定
    guardrails_enabled: bool = False
    guardrails_timeout: float = Field(default=3.0, gt=0)
    guardrails_on_timeout: Literal["fail-open", "fail-closed"] = "fail-closed"
    guardrails_on_error: Literal["fail-open", "fail-closed"] = "fail-closed"

    # プラグイン権限設定
    plugin_prompt_override_allowed: bool = False
    plugin_trusted_signatures: list[str] = Field(default_factory=list)

    # 本番運用モード
    production_mode: bool = False
    plugin_public_key_path: Optional[Path] = None

    # 出力設定
    output_format: Literal["json", "markdown"] = "markdown"

    @field_validator("plugin_public_key_path")
    @classmethod
    def validate_production_key_path(
        cls,
        value: Optional[Path],
        info: FieldValidationInfo,
    ) -> Optional[Path]:
        """production_mode 時は公開鍵パスを必須化"""
        if info.data.get("production_mode") and value is None:
            raise ValueError(
                "production_mode=True では plugin_public_key_path の明示指定が必須です"
            )
        return value

    def dump_masked(self) -> dict:
        """機微情報をマスクした設定を返却する"""
        data = self.model_dump()
        api_key = data.get("api_key")
        if api_key:
            data["api_key"] = (
                f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
            )
        return data
