"""LLMクライアント

Anthropic APIとの通信を管理するクライアント。
各エージェントが独立して思考を生成できるようにする。

Requirements: 2.1, 2.2, 2.3, 2.4
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, TYPE_CHECKING

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
from magi.core.concurrency import ConcurrencyController

if TYPE_CHECKING:
    from magi.models import Attachment

logger = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    """LLMリクエスト

    Attributes:
        system_prompt: システムプロンプト
        user_prompt: ユーザープロンプト
        max_tokens: 最大トークン数
        temperature: 温度パラメータ
        attachments: マルチモーダル添付ファイル（オプション）
    """

    system_prompt: str
    user_prompt: str
    max_tokens: int = 4096
    temperature: float = 0.7
    attachments: Optional[List["Attachment"]] = None


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
        temperature: デフォルトの温度パラメータ
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        retry_count: int = 3,
        timeout: int = 60,
        temperature: float = 0.7,
        base_delay_seconds: float = 0.5,
        rate_limit_backoff_cap: float = 60.0,
        default_backoff_cap: float = 10.0,
        rate_limit_retry_count: Optional[int] = None,
        default_retry_count: Optional[int] = None,
        min_rate_limit_backoff_seconds: float = 0.05,
        concurrency_controller: Optional[ConcurrencyController] = None,
    ):
        """LLMClientを初期化

        Args:
            api_key: Anthropic APIキー
            model: 使用するモデル名
            retry_count: リトライ回数
            timeout: タイムアウト秒数
            temperature: デフォルトの温度パラメータ (0.0-1.0)
            base_delay_seconds: バックオフ計算の基準秒数
            rate_limit_backoff_cap: レート制限時の待機上限秒数
            default_backoff_cap: その他エラー時の待機上限秒数
            rate_limit_retry_count: レート制限時の最大試行回数（未指定時は6回以上を保証）
            default_retry_count: その他エラー時の最大試行回数（未指定時はretry_countを3回上限で使用）
            min_rate_limit_backoff_seconds: レート制限時に必ず待機する最小秒数
            concurrency_controller: 同時実行制御およびレート制限記録を行うコントローラ
        """
        self.api_key = api_key
        self.model = model
        self.retry_count = retry_count
        self.timeout = timeout
        self.temperature = temperature
        self.base_delay_seconds = base_delay_seconds
        self.rate_limit_backoff_cap = rate_limit_backoff_cap
        self.default_backoff_cap = default_backoff_cap
        self.min_rate_limit_backoff_seconds = min_rate_limit_backoff_seconds
        self._concurrency_controller = concurrency_controller

        # レート制限時は少なくとも6回まで試行し、その他は最大3回までに制限
        configured_rate_limit_retry = (
            rate_limit_retry_count if rate_limit_retry_count is not None else 6
        )
        self.rate_limit_retry_count = max(
            1,
            min(configured_rate_limit_retry, 6),
        )

        configured_default_retry = (
            default_retry_count if default_retry_count is not None else self.retry_count
        )
        self.default_retry_count = max(1, min(configured_default_retry, 3))

        # Anthropicクライアントを初期化
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout)

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
        """指数バックオフ＋Full Jitterで再試行

        Args:
            request: LLMリクエスト

        Returns:
            LLMResponse: APIからのレスポンス

        Raises:
            MagiException: リトライ回数を超えた場合、または認証エラーの場合
        """
        last_error: Optional[MagiError] = None

        attempt = 0
        while True:
            try:
                return await self._send_request(request)
            except Exception as e:
                # エラーを分類
                error_type = self._classify_error(e)

                # レート制限発生を記録
                if (
                    error_type == APIErrorType.RATE_LIMIT
                    and self._concurrency_controller
                ):
                    self._concurrency_controller.note_rate_limit()

                # MagiErrorを作成
                magi_error = self._create_error_for_type(error_type, e)

                # 認証エラーの場合は即座にraise（リトライしない）
                if error_type == APIErrorType.AUTH_ERROR:
                    raise MagiException(magi_error) from e

                # last_errorにMagiErrorを保存
                last_error = magi_error

                max_attempts = self._max_attempts_for(error_type)
                if self._should_retry(error_type, attempt, max_attempts):
                    wait_time = self._calculate_backoff(error_type, attempt)
                    if error_type == APIErrorType.RATE_LIMIT:
                        logger.warning(
                            "Rate limit detected; backing off before retry",
                            extra={
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts,
                                "backoff_seconds": wait_time,
                            },
                        )
                    await asyncio.sleep(wait_time)
                    attempt += 1
                else:
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
        import base64

        # contentを配列形式で構築: テキスト + 添付ファイル
        content_blocks = [{"type": "text", "text": request.user_prompt}]

        # 添付ファイルがある場合、image content blockとして追加
        if request.attachments:
            for attachment in request.attachments:
                content_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": attachment.mime_type,
                            "data": base64.b64encode(attachment.data).decode("utf-8"),
                        },
                    }
                )

        # streamパラメータを解決(リクエストに指定があればそれを使い、なければデフォルトを使用)
        # ただし、Anthropic SDKのcreateメソッドはstreamパラメータを直接サポートしていないため、
        # 必要に応じてstream()メソッドを使用するか、stream=Trueを渡す必要があるが、
        # AsyncAnthropic.messages.create は stream引数を取る (ver 0.3.0以降)
        # ここでは request オブジェクトに stream 属性がないため、将来的な拡張性を考慮しつつ
        # 一旦は stream=False (デフォルト) で動作させる。
        # ユーザー要望にある「stream既定値の上流反映」は、もし request に stream 属性があれば
        # それを使うべきだが、現在の LLMRequest 定義には stream がない。
        # もし動的に追加された属性として stream がある場合を考慮する。
        is_stream = getattr(request, "stream", False)

        response = await self._client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            messages=[{"role": "user", "content": content_blocks}],
            temperature=request.temperature,
            stream=is_stream,
        )

        if is_stream:
            # ストリームの場合、ジェネレータを返す処理が必要だが、
            # 現在の LLMResponse は同期的なコンテンツを期待している。
            # ここではストリームを消費して結合する簡易実装とするか、
            # あるいは LLMResponse の設計を見直す必要がある。
            # 指示に従い「ハンドラで確定した stream を転送ボディに反映」する修正を行う。
            # SDKの場合、stream=Trueを指定するとAsyncStreamが返る。
            full_content = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in response:
                if chunk.type == "message_start":
                    if hasattr(chunk, "message") and hasattr(chunk.message, "usage"):
                        usage["input_tokens"] += getattr(
                            chunk.message.usage, "input_tokens", 0
                        )
                        usage["output_tokens"] += getattr(
                            chunk.message.usage, "output_tokens", 0
                        )

                elif chunk.type == "content_block_delta":
                    if hasattr(chunk, "delta") and hasattr(chunk.delta, "text"):
                        full_content += chunk.delta.text

                elif chunk.type == "message_delta":
                    if hasattr(chunk, "usage"):
                        usage["output_tokens"] = getattr(
                            chunk.usage, "output_tokens", usage["output_tokens"]
                        )

                elif chunk.type == "error":
                    error_details = getattr(chunk, "error", "Unknown stream error")
                    raise MagiException(
                        create_api_error(
                            ErrorCode.API_ERROR, f"Stream error: {error_details}"
                        )
                    )

            return LLMResponse(
                content=full_content,
                usage=usage,
                model=self.model,
            )

        # レスポンスを変換
        content = ""
        if response.content and len(response.content) > 0:
            content = response.content[0].text

        return LLMResponse(
            content=content,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            model=response.model,
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

    def _create_error_for_type(
        self, error_type: APIErrorType, original_error: Exception
    ) -> MagiError:
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
                True,
            ),
            APIErrorType.RATE_LIMIT: (
                ErrorCode.API_RATE_LIMIT,
                "APIのレート制限に達しました。しばらく待ってから再試行してください。",
                True,
            ),
            APIErrorType.AUTH_ERROR: (
                ErrorCode.API_AUTH_ERROR,
                "API認証に失敗しました。APIキーを確認してください。",
                False,
            ),
            APIErrorType.UNKNOWN: (
                ErrorCode.API_ERROR,
                "APIリクエストで予期しないエラーが発生しました。",
                True,
            ),
        }

        code, message, recoverable = error_map[error_type]
        return create_api_error(
            code=code,
            message=message,
            recoverable=recoverable,
            details={"error_type": type(original_error).__name__},
        )

    def _should_retry(
        self, error_type: APIErrorType, attempt: int, retry_count: int
    ) -> bool:
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

    def _max_attempts_for(self, error_type: APIErrorType) -> int:
        """エラー種別に応じた最大試行回数を返す。"""
        if error_type == APIErrorType.RATE_LIMIT:
            return self.rate_limit_retry_count
        return self.default_retry_count

    def _calculate_backoff(self, error_type: APIErrorType, attempt: int) -> float:
        """Full Jitter を用いた待機時間を計算する。"""
        cap = (
            self.rate_limit_backoff_cap
            if error_type == APIErrorType.RATE_LIMIT
            else self.default_backoff_cap
        )
        exponential = self.base_delay_seconds * (2**attempt)
        wait = random.uniform(0, min(cap, exponential))
        if error_type == APIErrorType.RATE_LIMIT:
            return max(self.min_rate_limit_backoff_seconds, wait)
        return wait

    async def close(self) -> None:
        """AsyncAnthropic クライアントをクリーンアップ"""
        if self._client is not None:
            await self._client.close()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()
