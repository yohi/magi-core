"""認証プロバイダ基盤。

LLM向けの認証プロバイダが共通で実装すべきインターフェースを定義する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class AuthContext:
    """認証に必要な設定情報。

    個別のプロバイダが必要とする値を保持するための共通コンテナ。
    """

    client_id: str | None = None
    client_secret: str | None = None
    scopes: list[str] = field(default_factory=list)
    auth_url: str | None = None
    token_url: str | None = None
    redirect_uri: str | None = None
    audience: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


class AuthProvider(ABC):
    """認証プロバイダの抽象基底クラス。

    認証フローの開始とアクセストークン取得の共通契約を表す。
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """認証フローを開始・完了する。"""

    @abstractmethod
    async def get_token(self) -> str:
        """有効なアクセストークンを返す。"""
