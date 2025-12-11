"""
エラー定義

MAGIシステムで使用されるエラーコードと例外クラス
"""

from dataclasses import dataclass, field
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

    # プラグインエラー
    PLUGIN_YAML_PARSE_ERROR = "PLUGIN_001"
    PLUGIN_COMMAND_FAILED = "PLUGIN_002"
    PLUGIN_COMMAND_TIMEOUT = "PLUGIN_003"

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
        super().__init__(f"[{error.code}] {error.message}")


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
        recoverable=False
    )


def create_api_error(
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    recoverable: bool = True
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
        recoverable=recoverable
    )


def create_plugin_error(
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None
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
        recoverable=False
    )


def create_agent_error(
    message: str,
    details: Optional[Dict[str, Any]] = None
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
        recoverable=True  # 他のエージェントは継続可能
    )
