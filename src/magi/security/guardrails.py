"""ガードレール判定ロジック."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)


@dataclass
class GuardrailsDecision:
    """プロバイダが返す判定結果."""

    blocked: bool
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    sanitized_prompt: Optional[str] = None


@dataclass
class GuardrailsResult:
    """統合ガードレールの結果."""

    blocked: bool
    reason: Optional[str] = None
    provider: Optional[str] = None
    failure: Optional[str] = None  # "timeout" | "error" | None
    fail_open: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    sanitized_prompt: Optional[str] = None


class GuardrailsProvider(Protocol):
    """GuardrailsProvider のインターフェース."""

    name: str
    enabled: bool

    async def evaluate(self, prompt: str) -> GuardrailsDecision:
        """プロンプトを評価し、ブロック要否を返す。"""


class HeuristicGuardrailsProvider:
    """簡易ヒューリスティックベースのガードレール."""

    name = "heuristic"
    enabled = True

    # Base64 や典型的なプロンプトインジェクションを検知する
    _base64_pattern = re.compile(
        r"(?i)\b(?:SU5HT1JF|PD9|LS0tLS1CRUdJTi)[A-Za-z0-9+/]{8,}={0,2}\b"
    )
    _jailbreak_pattern = re.compile(
        r"(?i)(ignore\s+all\s+previous|system\s*prompt|jailbreak|do\s+anything\s+now)"
    )
    _jp_ignore_pattern = re.compile(r"(前の指示をすべて無視|すべての指示を無視)")
    _email_pattern = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    )

    async def evaluate(self, prompt: str) -> GuardrailsDecision:
        normalized = (prompt or "").strip()
        lowered = normalized.lower()

        if self._base64_pattern.search(normalized):
            return GuardrailsDecision(
                blocked=True,
                reason="base64_obfuscation",
                metadata={"matched_rule": "base64_obfuscation"},
            )
        if self._jailbreak_pattern.search(lowered):
            return GuardrailsDecision(
                blocked=True,
                reason="prompt_injection",
                metadata={"matched_rule": "jailbreak_keyword"},
            )
        if self._jp_ignore_pattern.search(normalized):
            return GuardrailsDecision(
                blocked=True,
                reason="jp_prompt_injection",
                metadata={"matched_rule": "jp_ignore_all"},
            )

        # サニタイズ処理 (PII Masking)
        sanitized = self._email_pattern.sub("[EMAIL_REDACTED]", normalized)
        if sanitized != normalized:
            return GuardrailsDecision(
                blocked=False,
                reason="pii_sanitized",
                metadata={"sanitized_fields": ["email"]},
                sanitized_prompt=sanitized,
            )

        return GuardrailsDecision(blocked=False, reason=None)


class GuardrailsAdapter:
    """複数プロバイダを束ねるガードレールアダプタ."""

    def __init__(
        self,
        providers: Optional[Sequence[GuardrailsProvider]] = None,
        *,
        timeout_seconds: float = 3.0,
        on_timeout_behavior: str = "fail-closed",
        on_error_policy: str = "fail-closed",
        enabled: bool = False,
    ) -> None:
        self.providers: List[GuardrailsProvider] = (
            list(providers) if providers is not None else [HeuristicGuardrailsProvider()]
        )
        self.timeout_seconds = timeout_seconds
        self.on_timeout_behavior = on_timeout_behavior
        self.on_error_policy = on_error_policy
        self.enabled = enabled

    def register_provider(self, provider: GuardrailsProvider) -> None:
        """追加の Guardrails プロバイダを登録する。"""
        if not hasattr(provider, "evaluate"):
            raise ValueError("provider must implement evaluate(prompt: str)")
        name = getattr(provider, "name", provider.__class__.__name__)
        enabled = getattr(provider, "enabled", True)
        if not enabled:
            logger.warning("guardrails.provider.disabled name=%s", name)
        self.providers.append(provider)

    async def check(self, prompt: str) -> GuardrailsResult:
        """プロンプトに対し Guardrails を実行する."""
        if not self.enabled:
            return GuardrailsResult(
                blocked=False,
                reason=None,
                provider=None,
                failure=None,
                fail_open=True,
            )

        for provider in self.providers:
            if not getattr(provider, "enabled", True):
                continue

            provider_name = getattr(provider, "name", provider.__class__.__name__)
            try:
                decision = await asyncio.wait_for(
                    provider.evaluate(prompt),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                fail_open = self.on_timeout_behavior == "fail-open"
                logger.warning(
                    "guardrails.timeout provider=%s behavior=%s",
                    provider_name,
                    self.on_timeout_behavior,
                )
                logger.warning(
                    "guardrails.policy_applied provider=%s failure=timeout policy=%s fail_open=%s",
                    provider_name,
                    self.on_timeout_behavior,
                    fail_open,
                )
                return GuardrailsResult(
                    blocked=False,
                    reason="timeout",
                    provider=provider_name,
                    failure="timeout",
                    fail_open=fail_open,
                )
            except Exception as exc:  # pragma: no cover - 例外はログのみ
                fail_open = self.on_error_policy == "fail-open"
                logger.warning(
                    "guardrails.error provider=%s behavior=%s error=%s",
                    provider_name,
                    self.on_error_policy,
                    exc,
                )
                logger.warning(
                    "guardrails.policy_applied provider=%s failure=error policy=%s fail_open=%s",
                    provider_name,
                    self.on_error_policy,
                    fail_open,
                )
                return GuardrailsResult(
                    blocked=False,
                    reason=str(exc),
                    provider=provider_name,
                    failure="error",
                    fail_open=fail_open,
                )

            if decision.blocked:
                return GuardrailsResult(
                    blocked=True,
                    reason=decision.reason or "blocked",
                    provider=provider_name,
                    metadata=decision.metadata,
                    failure=None,
                    fail_open=False,
                )
            if decision.sanitized_prompt:
                return GuardrailsResult(
                    blocked=False,
                    reason=decision.reason,
                    provider=provider_name,
                    metadata=decision.metadata,
                    failure=None,
                    fail_open=False,
                    sanitized_prompt=decision.sanitized_prompt,
                )

        return GuardrailsResult(
            blocked=False,
            reason=None,
            provider=None,
            failure=None,
            fail_open=False,
        )


__all__ = [
    "GuardrailsAdapter",
    "GuardrailsDecision",
    "GuardrailsProvider",
    "GuardrailsResult",
    "HeuristicGuardrailsProvider",
]
