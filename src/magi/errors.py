"""
エラー定義

MAGIシステムで使用されるエラーコードと例外クラス
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(Enum):
    """エラーコード

    カテゴリ別にエラーコードを定義:
    - CONFIG_xxx: 設定エラー
    - API_xxx: APIエラー
    - PLUGIN_xxx: プラグインエラー
    - AGENT_xxx: エージェントエラー
    """
    # 設定エラー
    CONFIG_MISSING_API_KEY = "CONFIG_001"
    CONFIG_INVALID_VALUE = "CONFIG_002"

    # APIエラー
    API_TIMEOUT = "API_001"
    API_RATE_LIMIT = "API_002"
    API_AUTH_ERROR = "API_003"
    API_ERROR = "API_004"

    # プラグインエラー
    PLUGIN_YAML_PARSE_ERROR = "PLUGIN_001"
    PLUGIN_COMMAND_FAILED = "PLUGIN_002"
    PLUGIN_COMMAND_TIMEOUT = "PLUGIN_003"
    PLUGIN_LOAD_TIMEOUT = "PLUGIN_004"

    # エージェントエラー
    AGENT_THINKING_FAILED = "AGENT_001"

    # コンセンサスエンジンエラー
    CONSENSUS_SCHEMA_RETRY_EXCEEDED = "CONSENSUS_001"
    CONSENSUS_QUORUM_UNSATISFIED = "CONSENSUS_002"
    CONSENSUS_STREAMING_ABORTED = "CONSENSUS_003"

    # セキュリティエラー
    GUARDRAILS_TIMEOUT = "SECURITY_001"
    GUARDRAILS_BLOCKED = "SECURITY_002"
    GUARDRAILS_ERROR = "SECURITY_003"
    SIGNATURE_VERIFICATION_FAILED = "SECURITY_004"
    GUARDRAILS_FAIL_OPEN = "SECURITY_005"

    # リトライエラー
    RETRY_EXHAUSTED = "RETRY_001"


@dataclass
class MagiError:
    """MAGIエラー情報

    Attributes:
        code: エラーコード文字列
        message: エラーメッセージ
        details: 追加のエラー詳細情報
        recoverable: 復旧可能かどうか
    """
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    recoverable: bool = False
    log_level: int = logging.ERROR


class MagiException(Exception):
    """MAGI例外クラス

    MagiErrorをラップする例外クラス
    """

    def __init__(self, error: MagiError):
        """MagiExceptionを初期化

        Args:
            error: MagiErrorインスタンス
        """
        self.error = error
        self.log_level = error.log_level
        super().__init__(f"[{error.code}] {error.message}")


class ValidationException(MagiException):
    """バリデーション例外（入力/スキーマ関連）"""


class SecurityException(MagiException):
    """セキュリティ例外（Guardrails/署名関連）"""


class PluginValidationException(ValidationException):
    """プラグイン構文や署名の検証エラー"""


class RetryableException(MagiException):
    """一時的なエラーでリトライ可能な例外"""


class GuardrailsTimeoutException(SecurityException):
    """Guardrails のタイムアウト例外"""


class GuardrailsModelException(SecurityException):
    """Guardrails が危険と判定した場合の例外"""


ERROR_CODE_LOG_LEVEL: Dict[ErrorCode, int] = {
    ErrorCode.GUARDRAILS_FAIL_OPEN: logging.CRITICAL,
    ErrorCode.RETRY_EXHAUSTED: logging.ERROR,
    ErrorCode.GUARDRAILS_TIMEOUT: logging.ERROR,
    ErrorCode.GUARDRAILS_BLOCKED: logging.ERROR,
    ErrorCode.GUARDRAILS_ERROR: logging.ERROR,
    ErrorCode.SIGNATURE_VERIFICATION_FAILED: logging.ERROR,
    ErrorCode.PLUGIN_YAML_PARSE_ERROR: logging.ERROR,
}


# よく使用されるエラーのファクトリ関数
def create_config_error(message: str, details: Optional[Dict[str, Any]] = None) -> MagiError:
    """設定エラーを作成

    Args:
        message: エラーメッセージ
        details: 追加詳細

    Returns:
        MagiError: 設定エラー
    """
    return MagiError(
        code=ErrorCode.CONFIG_MISSING_API_KEY.value,
        message=message,
        details=details,
        recoverable=False,
        log_level=logging.ERROR,
    )


def create_api_error(
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    recoverable: bool = True,
    log_level: Optional[int] = None,
) -> MagiError:
    """APIエラーを作成

    Args:
        code: エラーコード
        message: エラーメッセージ
        details: 追加詳細
        recoverable: 復旧可能かどうか

    Returns:
        MagiError: APIエラー
    """
    return MagiError(
        code=code.value,
        message=message,
        details=details,
        recoverable=recoverable,
        log_level=log_level or ERROR_CODE_LOG_LEVEL.get(code, logging.ERROR),
    )


def create_plugin_error(
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    log_level: Optional[int] = None,
) -> MagiError:
    """プラグインエラーを作成

    Args:
        code: エラーコード
        message: エラーメッセージ
        details: 追加詳細

    Returns:
        MagiError: プラグインエラー
    """
    return MagiError(
        code=code.value,
        message=message,
        details=details,
        recoverable=False,
        log_level=log_level or ERROR_CODE_LOG_LEVEL.get(code, logging.ERROR),
    )


def create_agent_error(
    message: str,
    details: Optional[Dict[str, Any]] = None,
    log_level: int = logging.ERROR,
) -> MagiError:
    """エージェントエラーを作成

    Args:
        message: エラーメッセージ
        details: 追加詳細

    Returns:
        MagiError: エージェントエラー
    """
    return MagiError(
        code=ErrorCode.AGENT_THINKING_FAILED.value,
        message=message,
        details=details,
        recoverable=True,  # 他のエージェントは継続可能
        log_level=log_level,
    )
