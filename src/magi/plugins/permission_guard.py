"""プラグインによるプロンプト上書き権限を検証するガード。"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from magi.config.settings import MagiSettings

LOGGER = logging.getLogger(__name__)


class OverrideScope(Enum):
    """プロンプト変更の許可範囲。"""

    CONTEXT_ONLY = "context_only"
    FULL_OVERRIDE = "full_override"


@dataclass
class PermissionCheckResult:
    """権限チェックの結果。"""

    allowed: bool
    scope: OverrideScope
    reason: Optional[str] = None
    filtered_overrides: Dict[str, str] = field(default_factory=dict)


class PluginPermissionGuard:
    """プラグインのプロンプト上書き権限を検証する。"""

    def __init__(self, settings: MagiSettings) -> None:
        self.settings = settings

    def check_override_permission(
        self,
        plugin: Any,
        requested_overrides: Dict[str, str],
    ) -> PermissionCheckResult:
        """agent_overrides の権限を検証し、結果を返す。"""
        allowed_scope = self._resolve_allowed_scope()

        if not requested_overrides:
            return PermissionCheckResult(
                allowed=True,
                scope=allowed_scope,
                filtered_overrides={},
            )

        requested_scope = OverrideScope.FULL_OVERRIDE
        if not self._is_scope_allowed(requested_scope, allowed_scope):
            plugin_name = self._get_plugin_name(plugin)
            reason = "full override is disabled by configuration"
            LOGGER.warning(
                "plugin.override.denied plugin=%s requested_scope=%s allowed_scope=%s reason=%s",
                plugin_name,
                requested_scope.value,
                allowed_scope.value,
                reason,
            )
            return PermissionCheckResult(
                allowed=False,
                scope=allowed_scope,
                reason=reason,
                filtered_overrides={},
            )

        return PermissionCheckResult(
            allowed=True,
            scope=requested_scope,
            filtered_overrides=dict(requested_overrides),
        )

    def _resolve_allowed_scope(self) -> OverrideScope:
        """設定に基づき許可スコープを決定する。"""
        return (
            OverrideScope.FULL_OVERRIDE
            if self.settings.plugin_prompt_override_allowed
            else OverrideScope.CONTEXT_ONLY
        )

    @staticmethod
    def _is_scope_allowed(
        requested_scope: OverrideScope,
        allowed_scope: OverrideScope,
    ) -> bool:
        """要求されたスコープが許可されるかを判定する。"""
        if allowed_scope is OverrideScope.FULL_OVERRIDE:
            return True
        return requested_scope is OverrideScope.CONTEXT_ONLY

    @staticmethod
    def _get_plugin_name(plugin: Any) -> str:
        """ログ出力用にプラグイン名を解決する。"""
        metadata = getattr(plugin, "metadata", None)
        if metadata is not None:
            name = getattr(metadata, "name", None)
            if name:
                return str(name)
        name = getattr(plugin, "name", None)
        return str(name) if name else "unknown"
