""" 
MagiCLIメインモジュール

MAGIシステムのエントリーポイントとコマンドハンドラーの統合
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from magi import __version__
from magi.cli.parser import ArgumentParser, ParsedCommand, VALID_COMMANDS
from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.errors import MagiException, ErrorCode
from magi.output.formatter import OutputFormat, OutputFormatter
from magi.plugins.executor import CommandExecutor, CommandResult
from magi.plugins.guard import PluginGuard
from magi.plugins.loader import PluginLoader, Plugin


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

        question = " ".join(args).strip()
        if not question:
            print("Usage: magi ask <question>", file=sys.stderr)
            return 1

        audit_logger = logging.getLogger("magi.audit.ask")
        logging_configured = self._has_logging_destination(audit_logger)
        started_at = time.perf_counter()

        audit_logger.info(
            "consensus.ask.start",
            extra={
                "stage": "ask",
                "model": self.config.model,
                "question_preview": question[:80],
                "output_format": self.output_format.value,
            },
        )

        engine = ConsensusEngine(self.config)
        formatter = OutputFormatter()

        try:
            result = asyncio.run(engine.execute(question))
        except MagiException as exc:
            duration = time.perf_counter() - started_at
            audit_logger.error(
                "consensus.ask.error",
                extra={
                    "stage": "ask",
                    "model": self.config.model,
                    "duration_seconds": round(duration, 3),
                    "error": str(exc),
                },
            )
            print(f"合議処理でエラーが発生しました: {exc}", file=sys.stderr)
            if not logging_configured:
                print(
                    "警告: ログ出力先が設定されていません。監査ログを保存するには logging のハンドラを設定してください。",
                    file=sys.stderr,
                )
            return 1
        except Exception as exc:  # pragma: no cover - 想定外の例外
            duration = time.perf_counter() - started_at
            audit_logger.exception(
                "consensus.ask.exception",
                extra={
                    "stage": "ask",
                    "model": self.config.model,
                    "duration_seconds": round(duration, 3),
                },
            )
            print(
                f"合議処理で予期しないエラーが発生しました: {exc}",
                file=sys.stderr,
            )
            if not logging_configured:
                print(
                    "警告: ログ出力先が設定されていません。監査ログを保存するには logging のハンドラを設定してください。",
                    file=sys.stderr,
                )
            return 1

        duration = time.perf_counter() - started_at
        audit_logger.info(
            "consensus.ask.completed",
            extra={
                "stage": "ask",
                "model": self.config.model,
                "duration_seconds": round(duration, 3),
                "exit_code": result.exit_code,
            },
        )

        output = formatter.format(result, self.output_format)
        print(output)

        fail_safe = self._extract_fail_safe_summary(engine)
        if fail_safe is not None:
            audit_logger.warning(
                "consensus.ask.fail_safe",
                extra={
                    "stage": fail_safe.get("phase", "unknown"),
                    "reason": fail_safe.get("reason", ""),
                },
            )
            print(
                f"フェイルセーフ発生 ({fail_safe.get('phase', 'unknown')}): {fail_safe.get('reason', '理由不明')}",
                file=sys.stderr,
            )

        if not logging_configured:
            print(
                "警告: ログ出力先が設定されていません。監査ログを保存するには logging のハンドラを設定してください。",
                file=sys.stderr,
            )

        return result.exit_code

    def _run_spec_command(self, args: List[str]) -> int:
        """specコマンドの実行

        SDDプラグインを使用して仕様書を生成し、3賢者によるレビューを行う。

        Args:
            args: コマンド引数（仕様書作成のリクエスト）

        Returns:
            int: 終了コード
            
        Requirements:
            - 10.1: cc-sddコマンドを実行しドラフト仕様書を生成
            - 10.2: 仕様書の内容を3賢者のレビュー対象として提供
            - 10.3: 指摘事項を反映
            - 10.4: cc-sddが利用できない場合のエラー処理
        """
        if not args:
            print("Usage: magi spec <request>", file=sys.stderr)
            return 1

        request = " ".join(args)
        
        # プラグインパスの決定
        plugin_name = self.plugin or "magi-cc-sdd-plugin"
        plugin_path = self._find_plugin_path(plugin_name)
        
        if plugin_path is None:
            print(f"Error: Plugin '{plugin_name}' not found.", file=sys.stderr)
            print("Please ensure the plugin exists in the plugins directory.", file=sys.stderr)
            return 1
        
        # プラグインのロード
        try:
            loader = PluginLoader()
            plugin = loader.load(plugin_path)
        except MagiException as e:
            print(f"Error loading plugin: {e.error.message}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error loading plugin: {e}", file=sys.stderr)
            return 1
        
        print(f"Loaded plugin: {plugin.metadata.name} v{plugin.metadata.version}")
        print(f"Description: {plugin.metadata.description}")
        print()
        
        # cc-sddコマンドの実行
        try:
            result = self._execute_cc_sdd(plugin, request)
        except MagiException as e:
            if e.error.code == ErrorCode.PLUGIN_COMMAND_FAILED:
                print(f"Error: {e.error.message}", file=sys.stderr)
                print(f"cc-sdd command is not available. Please install it first:", file=sys.stderr)
                print(f"  pip install cc-sdd", file=sys.stderr)
                print(f"", file=sys.stderr)
                print(f"Alternatively, consider disabling this plugin.", file=sys.stderr)
            elif e.error.code == ErrorCode.PLUGIN_COMMAND_TIMEOUT:
                print(f"Error: {e.error.message}", file=sys.stderr)
            else:
                print(f"Error: {e.error.message}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error executing cc-sdd: {e}", file=sys.stderr)
            return 1
        
        if result.return_code != 0:
            print(f"cc-sdd command failed with exit code {result.return_code}", file=sys.stderr)
            if result.stderr:
                print(f"Error output: {result.stderr}", file=sys.stderr)
            return 1
        
        # 仕様書の内容を表示
        print("=" * 60)
        print("Generated Specification Draft")
        print("=" * 60)
        print(result.stdout)
        print("=" * 60)
        print()
        
        # 3賢者によるレビューの準備（TODO: ConsensusEngine統合）
        print("Note: 3賢者によるレビュー機能は現在開発中です。")
        print(f"Agent overrides loaded for personas: {', '.join(p.name for p in plugin.agent_overrides.keys())}")
        
        return 0
    
    def _find_plugin_path(self, plugin_name: str) -> Optional[Path]:
        """プラグインパスを検索
        
        Args:
            plugin_name: プラグイン名
            
        Returns:
            プラグインファイルのパス、見つからない場合はNone
        """
        # 複数の場所を検索
        search_paths = [
            # プロジェクトのpluginsディレクトリ
            Path(__file__).parent.parent.parent.parent / "plugins" / plugin_name / "plugin.yaml",
            # カレントディレクトリのplugins
            Path.cwd() / "plugins" / plugin_name / "plugin.yaml",
            # ユーザーのホームディレクトリ
            Path.home() / ".magi" / "plugins" / plugin_name / "plugin.yaml",
        ]
        
        for path in search_paths:
            if path.exists():
                return path
        
        return None
    
    def _execute_cc_sdd(self, plugin: Plugin, request: str) -> CommandResult:
        """cc-sddコマンドを実行
        
        Args:
            plugin: ロードされたプラグイン
            request: 仕様書作成のリクエスト
            
        Returns:
            CommandResult: コマンド実行結果
        """
        executor = CommandExecutor(timeout=plugin.bridge.timeout)
        guard = PluginGuard()
        safe_args = guard.validate(plugin.bridge.command, [request])

        # 非同期実行
        return asyncio.run(executor.execute(plugin.bridge.command, safe_args))

    def _has_logging_destination(self, logger: logging.Logger) -> bool:
        """ログ出力先が設定されているかを判定する"""
        if logger.handlers:
            return True
        return logger.hasHandlers()

    def _extract_fail_safe_summary(self, engine: ConsensusEngine) -> Optional[Dict[str, Any]]:
        """合議処理で発生したフェイルセーフの概要を抽出する"""
        events = getattr(engine, "events", [])
        for event in reversed(events):
            if event.get("type") == "quorum.fail_safe":
                return {
                    "phase": event.get("phase") or "voting",
                    "reason": event.get("reason", ""),
                }

        errors = getattr(engine, "errors", [])
        for error in reversed(errors):
            if "reason" in error or "error" in error:
                return {
                    "phase": error.get("phase", "unknown"),
                    "reason": error.get("reason") or error.get("error", ""),
                }

        return None

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
