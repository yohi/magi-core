"""
MagiCLIメインモジュール

MAGIシステムのエントリーポイントとコマンドハンドラーの統合
"""

import sys
from typing import List, Optional

from magi import __version__
from magi.config.manager import Config
from magi.cli.parser import ArgumentParser, ParsedCommand, VALID_COMMANDS
from magi.output.formatter import OutputFormat


class MagiCLI:
    """MAGIシステムのエントリーポイント"""

    def __init__(
        self,
        config: Config,
        output_format: OutputFormat = OutputFormat.MARKDOWN,
        plugin: Optional[str] = None
    ):
        """初期化

        Args:
            config: 設定オブジェクト
            output_format: 出力形式（デフォルト: MARKDOWN）
            plugin: 使用するプラグイン名（デフォルト: None）
        """
        self.config = config
        self.parser = ArgumentParser()
        self.output_format = output_format
        self.plugin = plugin

    def run(self, command: str, args: List[str]) -> int:
        """コマンドを実行し、Exit Codeを返す

        Args:
            command: コマンド名
            args: コマンド引数

        Returns:
            int: 終了コード（0: 成功、非0: エラー）
        """
        # ヘルプコマンド
        if command == "help":
            self.show_help()
            return 0

        # バージョンコマンド
        if command == "version":
            self.show_version()
            return 0

        # 有効なコマンドかチェック
        if command not in VALID_COMMANDS:
            print(
                f"Unknown command: '{command}'. "
                f"Available commands: {', '.join(sorted(VALID_COMMANDS))}",
                file=sys.stderr
            )
            return 1

        # askコマンド
        if command == "ask":
            return self._run_ask_command(args)

        # specコマンド
        if command == "spec":
            return self._run_spec_command(args)

        # 未実装のコマンド
        print(f"Command '{command}' is not yet implemented.", file=sys.stderr)
        return 1

    def _run_ask_command(self, args: List[str]) -> int:
        """askコマンドの実行

        Args:
            args: コマンド引数

        Returns:
            int: 終了コード
        """
        if not args:
            print("Usage: magi ask <question>", file=sys.stderr)
            return 1

        # TODO: ConsensusEngineを使用した実装
        print("ask command is not yet implemented.", file=sys.stderr)
        return 1

    def _run_spec_command(self, args: List[str]) -> int:
        """specコマンドの実行

        Args:
            args: コマンド引数

        Returns:
            int: 終了コード
        """
        if not args:
            print("Usage: magi spec <request>", file=sys.stderr)
            return 1

        # TODO: プラグインを使用した実装
        print("spec command is not yet implemented.", file=sys.stderr)
        return 1

    def show_help(self) -> None:
        """ヘルプメッセージを表示"""
        help_text = f"""MAGI System v{__version__} - 3賢者による合議プロセスを通じた多角的判断を提供するCLIツール

Usage:
    magi <command> [args] [options]

Commands:
    ask <question>   3賢者に質問を投げかけ、合議による回答を得る
    spec <request>   仕様書の作成とレビューを行う（プラグイン使用）
    help             このヘルプメッセージを表示
    version          バージョン情報を表示

Options:
    -h, --help           ヘルプメッセージを表示
    -v, --version        バージョン情報を表示
    --format <format>    出力形式を指定（json, markdown）
    --plugin <name>      使用するプラグインを指定

Examples:
    magi ask "このコードをレビューしてください"
    magi spec "ログイン機能の仕様書を作成"
    magi --format json ask "リファクタリングの提案"

詳細:
    MAGIシステムは、3つの異なる人格（MELCHIOR、BALTHASAR、CASPER）による
    合議プロセスを通じて、より多角的で信頼性の高い判断を提供します。

    - MELCHIOR-1: 論理・科学を担当（論理的整合性と事実に基づいた分析）
    - BALTHASAR-2: 倫理・保護を担当（リスク回避と現状維持を優先）
    - CASPER-3: 欲望・実利を担当（ユーザーの利益と効率を最優先）

詳細は https://github.com/yohi/magi-core を参照してください。
"""
        print(help_text)

    def show_version(self) -> None:
        """バージョン情報を表示"""
        print(f"magi {__version__}")
