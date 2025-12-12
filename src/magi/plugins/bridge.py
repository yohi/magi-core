"""
プロバイダコンテキスト付きで外部CLIを起動するブリッジアダプタ
"""

import os
import re
from typing import Iterable, Optional, Set

from magi.config.provider import SUPPORTED_PROVIDERS
from magi.core.providers import ProviderContext
from magi.errors import ErrorCode, MagiError, MagiException, create_plugin_error
from magi.plugins.executor import CommandExecutor, CommandResult
from magi.plugins.guard import PluginGuard


def _sanitize_stderr(stderr: Optional[str], max_length: int = 1000) -> str:
    """stderrをサニタイズしてシークレット情報をマスクする

    Args:
        stderr: 元のstderr文字列
        max_length: サニタイズ後の最大文字数

    Returns:
        サニタイズされたstderr文字列
    """
    if not stderr:
        return ""

    sanitized = stderr

    # 一般的なシークレットパターンをマスク
    # KEY|TOKEN|SECRET|PASSWORD を含むキー=値のパターン
    secret_patterns = [
        # 環境変数形式: KEY=value, TOKEN=value など
        (r'(\b(?:KEY|TOKEN|SECRET|PASSWORD|API_KEY|AUTH|CREDENTIAL|PASSWD)\s*[=:]\s*)([^\s\'"<>]+)', r'\1***MASKED***'),
        # JSON形式: "key": "value", "token": "value" など
        (r'("(?:key|token|secret|password|api_key|auth|credential|passwd)"\s*:\s*")([^"]+)', r'\1***MASKED***'),
        # URLクエリパラメータ: ?key=value&token=value など
        (r'([?&](?:key|token|secret|password|api_key|auth|credential|passwd)=)([^&\s\'"<>]+)', r'\1***MASKED***'),
    ]

    for pattern, replacement in secret_patterns:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    # 最大長に切り詰め
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "...<truncated>"

    return sanitized


class BridgeAdapter:
    """PluginGuardとCommandExecutorをまとめ、provider情報を安全に伝搬する"""

    def __init__(
        self,
        *,
        guard: Optional[PluginGuard] = None,
        executor: Optional[CommandExecutor] = None,
        supported_providers: Optional[Iterable[str]] = None,
    ) -> None:
        self.guard = guard or PluginGuard()
        self.executor = executor or CommandExecutor()
        self.supported_providers: Set[str] = set(
            p.lower() for p in (supported_providers or SUPPORTED_PROVIDERS)
        )

    async def invoke(
        self,
        command: str,
        args: list[str],
        provider: ProviderContext,
        *,
        extra_env: Optional[dict] = None,
    ) -> CommandResult:
        """外部CLIを実行し、認証エラーをprovider文脈付きで返す"""
        if provider.provider_id.lower() not in self.supported_providers:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"Provider '{provider.provider_id}' is not supported by this bridge.",
                    details={"provider": provider.provider_id},
                    recoverable=False,
                )
            )

        safe_args = self.guard.validate(command, args)
        # 最低限のホスト環境のみ許可する（シークレット漏洩防止）
        allowlist = ("PATH", "LANG", "LC_ALL", "TERM", "SHELL")
        env: dict[str, str] = {
            key: os.environ[key]
            for key in allowlist
            if key in os.environ
        }
        if extra_env:
            env.update({str(k): str(v) for k, v in extra_env.items()})
        # provider 由来の値は上書きされないよう最後に入れる
        env.update(
            {
                "MAGI_PROVIDER": provider.provider_id,
                "MAGI_PROVIDER_MODEL": provider.model,
                "MAGI_PROVIDER_API_KEY": provider.api_key,
            }
        )
        if provider.endpoint:
            env["MAGI_PROVIDER_ENDPOINT"] = provider.endpoint

        result = await self.executor.execute(command, safe_args, env=env)

        if result.return_code != 0:
            stderr_lower = (result.stderr or "").lower()
            if "auth" in stderr_lower or "unauthorized" in stderr_lower:
                # stderrをサニタイズしてシークレット情報をマスク
                sanitized_stderr = _sanitize_stderr(result.stderr)
                # providerを安全な形式に変換
                safe_provider = provider.to_safe_dict()
                raise MagiException(
                    create_plugin_error(
                        ErrorCode.PLUGIN_COMMAND_FAILED,
                        f"Authentication failed for provider '{provider.provider_id}'.",
                        details={
                            "provider": safe_provider,
                            "stderr": sanitized_stderr,
                            "return_code": result.return_code,
                        },
                    )
                )

        return result
