"""
コマンドライン引数の解析

argparseを使用したコマンド解析とバリデーション機能を提供
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from magi.output.formatter import OutputFormat


# 有効なコマンド一覧
VALID_COMMANDS = {"ask", "spec", "help", "version", "auth", "init"}


@dataclass
class ParsedCommand:
    """解析済みコマンド

    Attributes:
        command: コマンド名
        args: コマンド引数
        options: オプション辞書
        plugin: 使用するプラグイン名
        output_format: 出力形式
    """

    command: str
    args: List[str]
    options: Dict[str, Any]
    plugin: Optional[str]
    output_format: OutputFormat


@dataclass
class ValidationResult:
    """バリデーション結果

    Attributes:
        is_valid: 有効かどうか
        errors: エラーメッセージのリスト
    """

    is_valid: bool
    errors: List[str]


class ArgumentParser:
    """コマンドライン引数の解析"""

    def parse(self, argv: List[str]) -> ParsedCommand:
        """引数を解析してParsedCommandを返す

        Args:
            argv: コマンドライン引数リスト

        Returns:
            ParsedCommand: 解析結果
        """
        options: Dict[str, Any] = {}
        args: List[str] = []
        command: str = ""
        plugin: Optional[str] = None
        output_format: OutputFormat = OutputFormat.MARKDOWN

        i = 0
        while i < len(argv):
            arg = argv[i]

            # ヘルプオプション
            if arg in ("-h", "--help"):
                options["help"] = True
                i += 1
                continue

            # バージョンオプション
            if arg in ("-v", "--version"):
                options["version"] = True
                i += 1
                continue

            # 設定チェックオプション
            if arg == "--config-check":
                options["config_check"] = True
                i += 1
                continue

            # フォーマットオプション
            if arg == "--format":
                if i + 1 < len(argv):
                    format_value = argv[i + 1].lower()
                    if format_value == "json":
                        output_format = OutputFormat.JSON
                    elif format_value == "markdown":
                        output_format = OutputFormat.MARKDOWN
                    i += 2
                    continue
                else:
                    i += 1
                    continue

            # プラグインオプション
            if arg == "--plugin":
                if i + 1 < len(argv):
                    plugin = argv[i + 1]
                    i += 2
                    continue
                else:
                    i += 1
                    continue

            # プロバイダオプション
            if arg == "--provider":
                if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    options["provider"] = argv[i + 1].lower()
                    i += 2
                    continue
                i += 1
                continue

            # specレビューオプション
            if arg == "--review":
                options["review"] = True
                i += 1
                continue

            if arg in ("-f", "--force", "-y", "--yes"):
                options["force"] = True
                i += 1
                continue

            # コマンドまたは引数
            if not command and not arg.startswith("-"):
                command = arg
            else:
                if not arg.startswith("-"):
                    args.append(arg)

            i += 1

        return ParsedCommand(
            command=command,
            args=args,
            options=options,
            plugin=plugin,
            output_format=output_format,
        )

    def validate(self, parsed: ParsedCommand) -> ValidationResult:
        """解析結果の妥当性を検証

        Args:
            parsed: 解析済みコマンド

        Returns:
            ValidationResult: バリデーション結果
        """
        errors: List[str] = []

        # ヘルプ・バージョンオプションは常に有効
        if (
            parsed.options.get("help")
            or parsed.options.get("version")
            or parsed.options.get("config_check")
        ):
            return ValidationResult(is_valid=True, errors=[])

        # コマンドが空の場合
        if not parsed.command:
            errors.append("Command is required. Use --help for usage information.")
            return ValidationResult(is_valid=False, errors=errors)

        # 不明なコマンドの場合
        if parsed.command not in VALID_COMMANDS:
            errors.append(
                f"Unknown command: '{parsed.command}'. "
                f"Available commands: {', '.join(sorted(VALID_COMMANDS))}"
            )
            return ValidationResult(is_valid=False, errors=errors)

        return ValidationResult(is_valid=True, errors=[])
