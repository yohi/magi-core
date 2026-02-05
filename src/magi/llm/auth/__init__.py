"""LLM認証プロバイダの公開API。"""

from __future__ import annotations

from magi.llm.auth.antigravity import AntigravityAuthProvider
from magi.llm.auth.base import AuthContext, AuthProvider
from magi.llm.auth.claude import ClaudeAuthProvider
from magi.llm.auth.copilot import CopilotAuthProvider
from magi.llm.auth.openai_codex import OpenAICodexAuthProvider
from magi.llm.auth.storage import TokenManager

__all__ = [
    "AntigravityAuthProvider",
    "AuthContext",
    "AuthProvider",
    "ClaudeAuthProvider",
    "CopilotAuthProvider",
    "OpenAICodexAuthProvider",
    "TokenManager",
    "get_auth_provider",
]


def get_auth_provider(provider_type: str, context: AuthContext) -> AuthProvider:
    """認証プロバイダを生成する。

    Args:
        provider_type: 認証プロバイダ種別。
        context: 認証に必要な設定情報。

    Returns:
        認証プロバイダのインスタンス。

    Raises:
        ValueError: 未対応のプロバイダが指定された場合。
    """

    normalized = provider_type.lower()
    if normalized == "claude":
        return ClaudeAuthProvider(context)
    if normalized == "copilot":
        return CopilotAuthProvider(context)
    if normalized == "antigravity":
        return AntigravityAuthProvider(context)
    if normalized in {"openai_codex", "codex", "openai-codex"}:
        return OpenAICodexAuthProvider(context)
    raise ValueError(f"未対応の認証プロバイダです: {provider_type}")
