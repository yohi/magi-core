"""
設定管理

MAGIシステムの設定読み込みと管理を行う
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from magi.errors import ErrorCode, MagiError, MagiException


# 有効な設定値の定数
VALID_VOTING_THRESHOLDS = ("majority", "unanimous")
VALID_OUTPUT_FORMATS = ("json", "markdown")


@dataclass
class Config:
    """MAGI設定

    Attributes:
        api_key: Anthropic APIキー
        model: 使用するモデル名
        debate_rounds: Debateラウンド数
        voting_threshold: 投票閾値（"majority" または "unanimous"）
        output_format: 出力形式（"json" または "markdown"）
        timeout: APIタイムアウト秒数
        retry_count: リトライ回数
        token_budget: トークン予算
        quorum_threshold: クオーラム閾値
        stream_retry_count: ストリーミング送出のリトライ回数
    """
    api_key: str
    model: str = "claude-sonnet-4-20250514"
    debate_rounds: int = 1
    voting_threshold: str = "majority"
    output_format: str = "markdown"
    timeout: int = 60
    retry_count: int = 3
    token_budget: int = 8192
    schema_retry_count: int = 3
    template_ttl_seconds: int = 300
    vote_template_name: str = "vote_prompt"
    template_base_path: str = "templates"
    quorum_threshold: int = 2
    stream_retry_count: int = 5
    enable_streaming_output: bool = False
    streaming_queue_size: int = 100
    streaming_emit_timeout_seconds: float = 2.0
    log_context_reduction_key: bool = True
    enable_hardened_consensus: bool = True
    legacy_fallback_on_fail_safe: bool = False
    enable_guardrails: bool = False
    guardrails_timeout_seconds: float = 3.0
    guardrails_on_timeout_behavior: str = "fail-closed"
    guardrails_on_error_policy: str = "fail-closed"
    guardrails_providers: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """バリデーション結果

    Attributes:
        is_valid: バリデーションが成功したかどうか
        errors: エラーメッセージのリスト
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)


class ConfigManager:
    """設定の読み込みと管理

    環境変数と設定ファイルから設定を読み込み、管理する。
    環境変数は設定ファイルの値を上書きする。
    """

    # 環境変数名のマッピング
    ENV_PREFIX = "MAGI_"
    ENV_MAPPING = {
        "api_key": "MAGI_API_KEY",
        "model": "MAGI_MODEL",
        "debate_rounds": "MAGI_DEBATE_ROUNDS",
        "voting_threshold": "MAGI_VOTING_THRESHOLD",
        "output_format": "MAGI_OUTPUT_FORMAT",
        "timeout": "MAGI_TIMEOUT",
        "retry_count": "MAGI_RETRY_COUNT",
        "token_budget": "CONSENSUS_TOKEN_BUDGET",
        "schema_retry_count": "CONSENSUS_SUMMARY_RETRY_COUNT",
        "template_ttl_seconds": "CONSENSUS_TEMPLATE_TTL_SECONDS",
        "vote_template_name": "CONSENSUS_VOTE_TEMPLATE",
        "template_base_path": "CONSENSUS_TEMPLATE_BASE_PATH",
        "quorum_threshold": "CONSENSUS_QUORUM_THRESHOLD",
        "stream_retry_count": "MAGI_CLI_STREAM_RETRY_COUNT",
        "log_context_reduction_key": "LOG_CONTEXT_REDUCTION_KEY",
        "enable_hardened_consensus": "CONSENSUS_HARDENED_ENABLED",
        "legacy_fallback_on_fail_safe": "CONSENSUS_LEGACY_FALLBACK",
        "enable_streaming_output": "CONSENSUS_STREAMING_ENABLED",
        "streaming_queue_size": "CONSENSUS_STREAMING_QUEUE_SIZE",
        "streaming_emit_timeout_seconds": "CONSENSUS_STREAMING_EMIT_TIMEOUT",
        "enable_guardrails": "CONSENSUS_GUARDRAILS_ENABLED",
        "guardrails_timeout_seconds": "CONSENSUS_GUARDRAILS_TIMEOUT",
        "guardrails_on_timeout_behavior": "CONSENSUS_GUARDRAILS_TIMEOUT_BEHAVIOR",
        "guardrails_on_error_policy": "CONSENSUS_GUARDRAILS_ERROR_POLICY",
    }

    # 整数型の設定キー
    INT_KEYS = (
        "debate_rounds",
        "timeout",
        "retry_count",
        "token_budget",
        "schema_retry_count",
        "template_ttl_seconds",
        "quorum_threshold",
        "stream_retry_count",
        "streaming_queue_size",
    )
    FLOAT_KEYS = ("streaming_emit_timeout_seconds", "guardrails_timeout_seconds")
    BOOL_KEYS = (
        "log_context_reduction_key",
        "enable_hardened_consensus",
        "legacy_fallback_on_fail_safe",
        "enable_streaming_output",
        "enable_guardrails",
    )

    def __init__(self):
        """ConfigManagerを初期化"""
        self._config: Optional[Config] = None

    def load(
        self,
        config_path: Optional[Path] = None,
        force_reload: bool = False
    ) -> Config:
        """設定を読み込む

        Args:
            config_path: 設定ファイルのパス（省略時はデフォルトパスを検索）
            force_reload: キャッシュを無視して再読み込みするかどうか

        Returns:
            Config: 読み込んだ設定

        Raises:
            MagiException: APIキーが設定されていない場合
        """
        if self._config is not None and not force_reload:
            return self._config

        # 設定値を収集（優先順位: 環境変数 > ファイル > デフォルト）
        config_dict: Dict[str, Any] = {}

        # 1. ファイルから読み込み
        file_config = self._load_from_file(config_path)
        config_dict.update(file_config)

        # 2. 環境変数から読み込み（ファイル設定を上書き）
        env_config = self._load_from_env()
        config_dict.update(env_config)

        # APIキーの存在確認
        if "api_key" not in config_dict or not config_dict["api_key"]:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message="APIキーが設定されていません。環境変数 MAGI_API_KEY または設定ファイルで設定してください。",
                    recoverable=False
                )
            )

        # Configオブジェクトを作成
        self._config = Config(**config_dict)
        return self._config

    def _load_from_file(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """設定ファイルから読み込み

        Args:
            config_path: 設定ファイルのパス

        Returns:
            Dict[str, Any]: 読み込んだ設定値
        """
        if config_path is None:
            # デフォルトパスを検索
            for path in self._get_default_config_paths():
                if path.exists():
                    config_path = path
                    break

        if config_path is None or not config_path.exists():
            return {}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data is None:
                    return {}
                return self._normalize_config(data)
        except yaml.YAMLError:
            return {}

    def _load_from_env(self) -> Dict[str, Any]:
        """環境変数から読み込み

        Returns:
            Dict[str, Any]: 読み込んだ設定値
        """
        config: Dict[str, Any] = {}

        for key, env_var in self.ENV_MAPPING.items():
            value = os.environ.get(env_var)
            if value is not None:
                # 整数型の変換
                if key in self.INT_KEYS:
                    try:
                        config[key] = int(value)
                    except ValueError:
                        pass  # 無効な値は無視
                elif key in self.FLOAT_KEYS:
                    try:
                        config[key] = float(value)
                    except ValueError:
                        pass
                elif key in self.BOOL_KEYS:
                    config[key] = str(value).lower() not in ("0", "false", "off", "no", "")
                else:
                    config[key] = value

        return config

    def _get_default_config_paths(self) -> List[Path]:
        """デフォルトの設定ファイルパスを取得

        Returns:
            List[Path]: 検索する設定ファイルパスのリスト
        """
        paths = []

        # カレントディレクトリ
        paths.append(Path.cwd() / "magi.yaml")
        paths.append(Path.cwd() / "magi.yml")

        # ホームディレクトリ
        home = Path.home()
        paths.append(home / ".magi.yaml")
        paths.append(home / ".magi.yml")
        paths.append(home / ".config" / "magi" / "config.yaml")
        paths.append(home / ".config" / "magi" / "config.yml")

        return paths

    def _normalize_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """設定値を正規化

        Args:
            data: 生の設定データ

        Returns:
            Dict[str, Any]: 正規化された設定値
        """
        result: Dict[str, Any] = {}

        for key in self.ENV_MAPPING.keys():
            if key in data:
                value = data[key]
                # 整数型の変換
                if key in self.INT_KEYS:
                    try:
                        result[key] = int(value)
                    except (ValueError, TypeError):
                        pass  # 無効な値は無視
                elif key in self.FLOAT_KEYS:
                    try:
                        result[key] = float(value)
                    except (ValueError, TypeError):
                        pass
                elif key in self.BOOL_KEYS:
                    result[key] = bool(value) if isinstance(value, bool) else str(value).lower() not in ("0", "false", "off", "no", "")
                else:
                    result[key] = value

        guardrails_cfg = data.get("guardrails")
        if isinstance(guardrails_cfg, dict):
            if "enabled" in guardrails_cfg:
                result["enable_guardrails"] = bool(guardrails_cfg.get("enabled"))
            if "timeout_seconds" in guardrails_cfg:
                try:
                    result["guardrails_timeout_seconds"] = float(
                        guardrails_cfg.get("timeout_seconds")
                    )
                except (ValueError, TypeError):
                    pass
            if "on_timeout_behavior" in guardrails_cfg:
                result["guardrails_on_timeout_behavior"] = str(
                    guardrails_cfg.get("on_timeout_behavior")
                )
            if "on_error_policy" in guardrails_cfg:
                result["guardrails_on_error_policy"] = str(
                    guardrails_cfg.get("on_error_policy")
                )
            if isinstance(guardrails_cfg.get("providers"), dict):
                result["guardrails_providers"] = guardrails_cfg.get("providers")

        streaming_cfg = data.get("streaming")
        if isinstance(streaming_cfg, dict):
            emitter_cfg = streaming_cfg.get("emitter", {})
            if isinstance(emitter_cfg, dict):
                if "queue_size" in emitter_cfg:
                    try:
                        result["streaming_queue_size"] = int(
                            emitter_cfg.get("queue_size")
                        )
                    except (ValueError, TypeError):
                        pass
                if "emit_timeout_seconds" in emitter_cfg:
                    try:
                        result["streaming_emit_timeout_seconds"] = float(
                            emitter_cfg.get("emit_timeout_seconds")
                        )
                    except (ValueError, TypeError):
                        pass

        return result

    def validate(self, config: Config) -> ValidationResult:
        """設定の妥当性を検証

        Args:
            config: 検証する設定

        Returns:
            ValidationResult: バリデーション結果
        """
        errors: List[str] = []

        # APIキーの検証
        if not config.api_key or not config.api_key.strip():
            errors.append("api_key: APIキーが空です")

        # voting_thresholdの検証
        if config.voting_threshold not in VALID_VOTING_THRESHOLDS:
            errors.append(
                f"voting_threshold: 無効な値です '{config.voting_threshold}'。"
                f"有効な値: {VALID_VOTING_THRESHOLDS}"
            )

        # output_formatの検証
        if config.output_format not in VALID_OUTPUT_FORMATS:
            errors.append(
                f"output_format: 無効な値です '{config.output_format}'。"
                f"有効な値: {VALID_OUTPUT_FORMATS}"
            )

        # debate_roundsの検証
        if config.debate_rounds <= 0:
            errors.append(
                f"debate_rounds: 1以上の値を指定してください（現在: {config.debate_rounds}）"
            )

        # timeoutの検証
        if config.timeout <= 0:
            errors.append(
                f"timeout: 1以上の値を指定してください（現在: {config.timeout}）"
            )

        # retry_countの検証
        if config.retry_count < 0:
            errors.append(
                f"retry_count: 0以上の値を指定してください（現在: {config.retry_count}）"
            )

        # token_budgetの検証
        if config.token_budget <= 0:
            errors.append(
                f"token_budget: 1以上の値を指定してください（現在: {config.token_budget}）"
            )

        if config.schema_retry_count < 0 or config.schema_retry_count > 10:
            errors.append(
                f"schema_retry_count: 0〜10 の範囲で指定してください（現在: {config.schema_retry_count}）"
            )

        if config.template_ttl_seconds <= 0:
            errors.append(
                f"template_ttl_seconds: 1以上の値を指定してください（現在: {config.template_ttl_seconds}）"
            )

        if config.quorum_threshold <= 0:
            errors.append(
                f"quorum_threshold: 1以上の値を指定してください（現在: {config.quorum_threshold}）"
            )

        if config.stream_retry_count < 0:
            errors.append(
                f"stream_retry_count: 0以上の値を指定してください（現在: {config.stream_retry_count}）"
            )
        if getattr(config, "streaming_queue_size", 1) <= 0:
            errors.append(
                f"streaming_queue_size: 1以上の値を指定してください（現在: {config.streaming_queue_size}）"
            )
        if getattr(config, "streaming_emit_timeout_seconds", 0.0) <= 0:
            errors.append(
                "streaming_emit_timeout_seconds: 0より大きい値を指定してください"
            )
        if getattr(config, "guardrails_timeout_seconds", 0) <= 0:
            errors.append(
                "guardrails_timeout_seconds: 0より大きい値を指定してください"
            )
        if getattr(config, "guardrails_on_timeout_behavior", "") not in (
            "fail-open",
            "fail-closed",
        ):
            errors.append(
                "guardrails_on_timeout_behavior: fail-open または fail-closed を指定してください"
            )
        if getattr(config, "guardrails_on_error_policy", "") not in (
            "fail-open",
            "fail-closed",
        ):
            errors.append(
                "guardrails_on_error_policy: fail-open または fail-closed を指定してください"
            )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )
