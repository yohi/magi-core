"""LLMクライアント

Anthropic APIとの通信を管理するクライアント。
各エージェントが独立して思考を生成できるようにする。

Requirements: 2.1, 2.2, 2.3, 2.4
"""
import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional

import anthropic
from anthropic import (
    Anthropic,
    AsyncAnthropic,
    APITimeoutError,
    RateLimitError,
    AuthenticationError,
    APIError,
)

from magi.errors import ErrorCode, MagiError, MagiException, create_api_error


@dataclass
class LLMRequest:
    """LLMリクエスト

    Attributes:
        system_prompt: システムプロンプト
        user_prompt: ユーザープロンプト
        max_tokens: 最大トークン数
        temperature: 温度パラメータ
    """
    system_prompt: str
    user_prompt: str
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class LLMResponse:
    """LLMレスポンス

    Attributes:
        content: レスポンス内容
        usage: トークン使用量
        model: 使用されたモデル
    """
    content: str
    usage: Dict[str, int]
    model: str


class APIErrorType(Enum):
    """APIエラータイプ

    APIから返される可能性のあるエラータイプを分類する。
    """
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH_ERROR = "auth_error"
    UNKNOWN = "unknown"


class LLMClient:
    """Anthropic APIクライアント

    Anthropic APIとの通信を管理し、各エージェントが独立して
    思考を生成できるようにする。

    Attributes:
        api_key: Anthropic APIキー
        model: 使用するモデル名
        retry_count: リトライ回数
        timeout: タイムアウト秒数
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-sonnet-20240229",
        retry_count: int = 3,
        timeout: int = 60
    ):
        """LLMClientを初期化

        Args:
            api_key: Anthropic APIキー
            model: 使用するモデル名
            retry_count: リトライ回数
            timeout: タイムアウト秒数
        """
        self.api_key = api_key
        self.model = model
        self.retry_count = retry_count
        self.timeout = timeout

        # Anthropicクライアントを初期化
        self._client = AsyncAnthropic(
            api_key=api_key,
            timeout=timeout
        )

    async def send(self, request: LLMRequest) -> LLMResponse:
        """APIリクエストを送信

        Args:
            request: LLMリクエスト

        Returns:
            LLMResponse: APIからのレスポンス

        Raises:
            MagiException: APIエラーが発生した場合
        """
        return await self._retry_with_backoff(request)

    async def _retry_with_backoff(self, request: LLMRequest) -> LLMResponse:
        """指数バックオフで再試行

        Args:
            request: LLMリクエスト

        Returns:
            LLMResponse: APIからのレスポンス

        Raises:
            MagiException: リトライ回数を超えた場合、または認証エラーの場合
        """
        last_error: Optional[MagiError] = None

        for attempt in range(self.retry_count):
            try:
                return await self._send_request(request)
            except Exception as e:
                # エラーを分類
                error_type = self._classify_error(e)

                # MagiErrorを作成
                magi_error = self._create_error_for_type(error_type, e)

                # 認証エラーの場合は即座にraise（リトライしない）
                if error_type == APIErrorType.AUTH_ERROR:
                    raise MagiException(magi_error) from e

                # last_errorにMagiErrorを保存
                last_error = magi_error

                # リトライすべきか判定
                if self._should_retry(error_type, attempt, self.retry_count):
                    # エラータイプに応じたバックオフ時間を計算
                    if error_type == APIErrorType.RATE_LIMIT:
                        # レート制限の場合は長めに待機
                        wait_time = (2 ** attempt) * 1.0
                    else:
                        # その他のエラーは標準的なバックオフ
                        wait_time = (2 ** attempt) * 0.5
                    await asyncio.sleep(wait_time)
                else:
                    # リトライしない場合はループを抜ける
                    break

        # 全てのリトライが失敗した場合、MagiExceptionをraise
        if last_error:
            raise MagiException(last_error)

        # ここには到達しないはず
        raise RuntimeError("予期しないエラー")

    async def _send_request(self, request: LLMRequest) -> LLMResponse:
        """実際のAPIリクエストを送信

        Args:
            request: LLMリクエスト

        Returns:
            LLMResponse: APIからのレスポンス
        """
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            messages=[
                {"role": "user", "content": request.user_prompt}
            ],
            temperature=request.temperature
        )

        # レスポンスを変換
        content = ""
        if response.content and len(response.content) > 0:
            content = response.content[0].text

        return LLMResponse(
            content=content,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            },
            model=response.model
        )

    def _classify_error(self, error: Exception) -> APIErrorType:
        """例外をAPIErrorTypeに分類

        Args:
            error: 発生した例外

        Returns:
            APIErrorType: 分類されたエラータイプ
        """
        if isinstance(error, (APITimeoutError, asyncio.TimeoutError, TimeoutError)):
            return APIErrorType.TIMEOUT
        elif isinstance(error, RateLimitError):
            return APIErrorType.RATE_LIMIT
        elif isinstance(error, AuthenticationError):
            return APIErrorType.AUTH_ERROR
        else:
            return APIErrorType.UNKNOWN

    def _create_error_for_type(self, error_type: APIErrorType, original_error: Exception) -> MagiError:
        """エラータイプに応じたMagiErrorを作成

        Requirements: 2.3 - APIがエラーレスポンスを返す場合、
        エラー種別に応じた適切なエラーメッセージを生成する

        Args:
            error_type: APIエラータイプ
            original_error: 元の例外

        Returns:
            MagiError: 対応するMagiError
        """
        error_map = {
            APIErrorType.TIMEOUT: (
                ErrorCode.API_TIMEOUT,
                "APIリクエストがタイムアウトしました。再試行してください。",
                True
            ),
            APIErrorType.RATE_LIMIT: (
                ErrorCode.API_RATE_LIMIT,
                "APIのレート制限に達しました。しばらく待ってから再試行してください。",
                True
            ),
            APIErrorType.AUTH_ERROR: (
                ErrorCode.API_AUTH_ERROR,
                "API認証に失敗しました。APIキーを確認してください。",
                False
            ),
            APIErrorType.UNKNOWN: (
                ErrorCode.API_TIMEOUT,
                "APIリクエストで予期しないエラーが発生しました。",
                True
            ),
        }

        code, message, recoverable = error_map[error_type]
        return create_api_error(
            code=code,
            message=message,
            recoverable=recoverable
        )

    def _should_retry(self, error_type: APIErrorType, attempt: int, retry_count: int) -> bool:
        """エラータイプに基づいてリトライすべきかを判定

        Args:
            error_type: APIエラータイプ
            attempt: 現在の試行回数（0始まり）
            retry_count: 最大リトライ回数

        Returns:
            bool: リトライすべきならTrue
        """
        # 認証エラーはリトライしない
        if error_type == APIErrorType.AUTH_ERROR:
            return False
        # 最大試行回数に達していない場合はリトライ
        return attempt < retry_count - 1
