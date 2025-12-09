"""プラグイン実行時の安全性検証を行うガード"""

import re
from typing import Iterable, List

from magi.errors import MagiException, create_plugin_error, ErrorCode

# ホワイトリストパターン（デフォルト許可文字）
COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9_\-./]+$")
# 引数の許容パターン（メタ文字を禁止しつつ空白や日本語は許可）
ARG_PATTERN = re.compile(r"^[^\$;\|><`&\\\*\?\{\}\[\]~\n\r\t]+$")


class PluginGuard:
    """プラグインコマンドの検証を担当"""

    def validate(self, command: str, args: Iterable[str]) -> List[str]:
        """コマンドと引数を検証し、安全な引数リストを返す

        コマンドはホワイトリスト文字のみを許可し、引数はメタ文字を含まないことを確認する。
        """
        if not COMMAND_PATTERN.match(command):
            raise MagiException(
                create_plugin_error(
                    ErrorCode.PLUGIN_YAML_PARSE_ERROR,
                    f"Command contains forbidden characters: {command}",
                )
            )

        sanitized_args: List[str] = []
        for arg in args:
            if arg is None:
                continue
            if not ARG_PATTERN.match(arg):
                raise MagiException(
                    create_plugin_error(
                        ErrorCode.PLUGIN_COMMAND_FAILED,
                        f"Argument contains forbidden characters: {arg}",
                    )
                )
            sanitized_args.append(arg)

        return sanitized_args
