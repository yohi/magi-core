"""
MagiCLIメインモジュール

MAGIシステムのエントリーポイントとコマンドハンドラーの統合
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional

from magi import __version__
from magi.cli.parser import ArgumentParser, ParsedCommand, VALID_COMMANDS
from magi.config.manager import Config
from magi.config.provider import DEFAULT_PROVIDER_ID, SUPPORTED_PROVIDERS
from magi.core.concurrency import ConcurrencyController
from magi.core.consensus import ConsensusEngine
from magi.core.providers import ProviderAdapterFactory, ProviderContext, ProviderSelector
from magi.errors import MagiError, MagiException, ErrorCode
from magi.llm.client import LLMClient
from magi.output.formatter import OutputFormat, OutputFormatter
from magi.plugins.bridge import BridgeAdapter
from magi.plugins.executor import CommandExecutor, CommandResult
from magi.plugins.guard import PluginGuard

if TYPE_CHECKING:
    from magi.plugins.loader import Plugin


class MagiCLI:
    """MAGIシステムのエントリーポイント"""

    REVIEW_RETRY_DEFAULTS: ClassVar[Dict[str, Any]] = {
        "max_attempts": 3,
        "wait_seconds": 1.0,
        "per_attempt_timeout": 5,
        "global_timeout": 15,
        "backoff_strategy": "fixed",
    }

    def __init__(
        self,
        config: Config,
        output_format: OutputFormat = OutputFormat.MARKDOWN,
        plugin: Optional[str] = None,
        provider_selector: Optional[ProviderSelector] = None,
        provider_factory: Optional[ProviderAdapterFactory] = None,
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
        self.provider_selector = provider_selector
        self.provider_factory = provider_factory or ProviderAdapterFactory()

    def run(self, command: str, args: List[str], options: Dict[str, Any] | None = None) -> int:
        """コマンドを実行し、Exit Codeを返す

        Args:
            command: コマンド名
            args: コマンド引数
            options: 解析済みオプション辞書

        Returns:
            int: 終了コード（0: 成功、非0: エラー）
        """
        if options is None:
            options = {}

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
            return self._run_ask_command(args, options)

        # specコマンド
        if command == "spec":
            return self._run_spec_command(args, options)

        # 未実装のコマンド
        print(f"Command '{command}' is not yet implemented.", file=sys.stderr)
        return 1

    def _run_ask_command(
        self,
        args: List[str],
        options: Optional[Dict[str, Any]] = None,
    ) -> int:
        """askコマンドの実行

        Args:
            args: コマンド引数

        Returns:
            int: 終了コード
        """
        options = options or {}
        if not args:
            print("Usage: magi ask <question>", file=sys.stderr)
            return 1

        question = " ".join(args).strip()
        if not question:
            print("Usage: magi ask <question>", file=sys.stderr)
            return 1

        try:
            provider = self._select_provider(options)
            concurrency_controller = ConcurrencyController(
                max_concurrent=getattr(self.config, "llm_concurrency_limit", 5)
            )
            llm_client = self._build_llm_client(
                provider,
                concurrency_controller=concurrency_controller,
            )
        except MagiException as exc:
            print(f"プロバイダ選択エラー: {exc.error.message}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover - 想定外の例外
            print(f"プロバイダ選択エラー: {exc}", file=sys.stderr)
            return 1

        # コンフィグのモデル/APIキーを選択結果に合わせて更新（監査ログ用）
        self.config.api_key = provider.api_key
        self.config.model = provider.model
        self._print_provider_selection(provider)

        audit_logger = logging.getLogger("magi.audit.ask")
        logging_configured = self._has_logging_destination(audit_logger)
        started_at = time.perf_counter()

        audit_logger.info(
            "consensus.ask.start",
            extra={
                "stage": "ask",
                "model": self.config.model,
                "provider": provider.provider_id,
                "used_default_provider": provider.used_default,
                "question_preview": question[:80],
                "output_format": self.output_format.value,
            },
        )

        engine = ConsensusEngine(
            self.config,
            llm_client_factory=lambda: llm_client,
            event_context={"provider": provider.provider_id},
            concurrency_controller=concurrency_controller,
        )
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
                    "provider": provider.provider_id,
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
                    "provider": provider.provider_id,
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

    def _run_spec_command(self, args: List[str], options: Optional[Dict[str, Any]] = None) -> int:
        """specコマンドの実行

        SDDプラグインを使用して仕様書を生成し、必要に応じて3賢者レビューを統合表示する。

        Args:
            args: コマンド引数（仕様書作成のリクエスト）
            options: 解析済みオプション辞書

        Returns:
            int: 終了コード
        """
        options = options or {}
        from magi.plugins.loader import PluginLoader
        review_requested, normalized_args = self._split_spec_args(args, options)

        if not normalized_args:
            print("Usage: magi spec <request>", file=sys.stderr)
            return 1

        request = " ".join(normalized_args)

        plugin_name = self.plugin or "magi-cc-sdd-plugin"
        plugin_path = self._find_plugin_path(plugin_name)

        if plugin_path is None:
            print(f"Error: Plugin '{plugin_name}' not found.", file=sys.stderr)
            print("Please ensure the plugin exists in the plugins directory.", file=sys.stderr)
            return 1

        try:
            loader = PluginLoader(config=self.config)
            plugin = loader.load(plugin_path)
        except MagiException as e:
            print(f"Error loading plugin: {e.error.message}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error loading plugin: {e}", file=sys.stderr)
            return 1

        try:
            provider = self._select_provider(options)
        except MagiException as exc:
            print(f"プロバイダ選択エラー: {exc.error.message}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover - 想定外の例外
            print(f"プロバイダ選択エラー: {exc}", file=sys.stderr)
            return 1

        self.config.api_key = provider.api_key
        self.config.model = provider.model
        self._print_provider_selection(provider)

        print(f"Loaded plugin: {plugin.metadata.name} v{plugin.metadata.version}")
        print(f"Description: {plugin.metadata.description}")
        print()

        if review_requested:
            return self._run_spec_with_review(plugin, request, provider)

        try:
            result = self._execute_cc_sdd(plugin, request, provider_context=provider)
        except MagiException as e:
            if e.error.code == ErrorCode.PLUGIN_COMMAND_FAILED:
                print(f"Error: {e.error.message}", file=sys.stderr)
                print("cc-sdd command is not available. Please install it first:", file=sys.stderr)
                print("  pip install cc-sdd", file=sys.stderr)
                print("", file=sys.stderr)
                print("Alternatively, consider disabling this plugin.", file=sys.stderr)
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

        print("=" * 60)
        print("Generated Specification Draft")
        print("=" * 60)
        print(result.stdout)
        print("=" * 60)
        print()
        print("Note: 3賢者レビューを実行する場合は --review を指定してください。")
        print(f"Agent overrides loaded for personas: {', '.join(p.name for p in plugin.agent_overrides.keys())}")

        return 0

    def _run_spec_with_review(
        self,
        plugin: Plugin,
        request: str,
        provider_context: ProviderContext,
    ) -> int:
        """`magi spec --review` フローの実行"""
        review_config = dict(self.REVIEW_RETRY_DEFAULTS)
        print(
            "[review] retry policy: "
            f"max_attempts={review_config['max_attempts']}, "
            f"wait={review_config['wait_seconds']}s, "
            f"per_attempt_timeout={review_config['per_attempt_timeout']}s, "
            f"global_timeout={review_config['global_timeout']}s"
        )

        attempt = 0
        start_time = time.monotonic()
        last_errors: List[str] = []
        parsed_reviews: List[Dict[str, Any]] = []
        spec_text: Optional[str] = None

        while attempt < review_config["max_attempts"]:
            attempt += 1

            if time.monotonic() - start_time > review_config["global_timeout"]:
                last_errors.append("レビュー実行がグローバルタイムアウトを超過しました。")
                break

            try:
                result = self._execute_cc_sdd(
                    plugin,
                    request,
                    extra_args=["--review", "--format", "json"],
                    timeout=review_config["per_attempt_timeout"],
                    provider_context=provider_context,
                )
            except MagiException as exc:
                last_errors.append(exc.error.message if hasattr(exc, "error") else str(exc))
                self._print_review_retry_status(attempt, review_config)
                if attempt < review_config["max_attempts"]:
                    time.sleep(review_config["wait_seconds"])
                continue
            except Exception as exc:  # pylint: disable=broad-except
                last_errors.append(str(exc))
                self._print_review_retry_status(attempt, review_config)
                if attempt < review_config["max_attempts"]:
                    time.sleep(review_config["wait_seconds"])
                continue

            if result.return_code != 0:
                last_errors.append(
                    f"cc-sdd command failed (attempt {attempt}): {result.stderr or 'no stderr'}"
                )
                self._print_review_retry_status(attempt, review_config)
                if attempt < review_config["max_attempts"]:
                    time.sleep(review_config["wait_seconds"])
                continue

            spec_text, parsed_reviews, parse_errors = self._parse_review_output(result.stdout)
            if parse_errors:
                last_errors.extend(parse_errors)

            if parsed_reviews:
                break

            self._print_review_retry_status(attempt, review_config)
            if attempt < review_config["max_attempts"]:
                time.sleep(review_config["wait_seconds"])

        if not parsed_reviews:
            print("レビュー結果を取得できませんでした。", file=sys.stderr)
            if last_errors:
                print("\n".join(dict.fromkeys(last_errors)), file=sys.stderr)
            return 1

        self._render_review_results(spec_text, parsed_reviews, review_config)

        if last_errors:
            print("\n".join(dict.fromkeys(last_errors)), file=sys.stderr)

        return 0

    def _split_spec_args(self, args: List[str], options: Dict[str, Any]) -> tuple[bool, List[str]]:
        """spec引数と--reviewフラグを正規化"""
        review_requested = bool(options.get("review"))
        normalized_args: List[str] = []

        for arg in args:
            if arg == "--review":
                review_requested = True
                continue
            normalized_args.append(arg)

        return review_requested, normalized_args

    def _parse_review_output(
        self, raw_output: str
    ) -> tuple[Optional[str], List[Dict[str, Any]], List[str]]:
        """cc-sdd出力から仕様とレビュー配列を抽出"""
        errors: List[str] = []
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            errors.append("レビュー出力がJSON形式ではありません。")
            return raw_output.strip(), [], errors

        spec_text = payload.get("spec") if isinstance(payload.get("spec"), str) else None
        raw_reviews = payload.get("reviews", [])

        if not isinstance(raw_reviews, list):
            errors.append("reviews は配列である必要があります。")
            return spec_text, [], errors

        parsed: List[Dict[str, Any]] = []
        required_keys = {"reviewer_id", "status", "score", "message", "timestamp"}

        for entry in raw_reviews:
            if not isinstance(entry, dict):
                errors.append("レビューエントリが辞書ではありません。")
                continue

            missing = required_keys - set(entry.keys())
            if missing:
                errors.append(
                    f"{entry.get('reviewer_id', 'unknown')} のフィールド不足: {', '.join(sorted(missing))}"
                )
                continue

            try:
                score_value = float(entry["score"])
            except (TypeError, ValueError):
                errors.append(f"{entry.get('reviewer_id', 'unknown')} のscoreが数値ではありません。")
                continue

            parsed.append(
                {
                    "reviewer_id": str(entry["reviewer_id"]),
                    "status": str(entry["status"]),
                    "score": score_value,
                    "message": str(entry["message"]),
                    "timestamp": str(entry["timestamp"]),
                }
            )

        return spec_text, parsed, errors

    def _render_review_results(
        self, spec_text: Optional[str], reviews: List[Dict[str, Any]], review_config: Dict[str, Any]
    ) -> None:
        """レビュー結果を整形表示"""
        if spec_text:
            print("=" * 60)
            print("Generated Specification Draft")
            print("=" * 60)
            print(spec_text)
            print("=" * 60)
            print()

        success_statuses = {"ok", "approved", "success", "completed", "done"}
        failure_statuses = {"failed", "error", "timeout"}
        completed = 0

        for entry in reviews:
            status = entry["status"].lower()
            icon = "✔" if status in success_statuses else "✖" if status in failure_statuses else "…"
            if status in success_statuses:
                completed += 1
            score = entry["score"]
            message = entry["message"]
            reviewer_id = entry["reviewer_id"]
            print(f"[{icon}] {reviewer_id} {score:.2f} \"{message}\" ({status})")

        if reviews:
            print(
                "[…] overall "
                f"{completed}/{len(reviews)} complete "
                f"(max_attempts={review_config['max_attempts']}, "
                f"wait={review_config['wait_seconds']}s, "
                f"per_attempt_timeout={review_config['per_attempt_timeout']}s, "
                f"global_timeout={review_config['global_timeout']}s)"
            )

    def _print_review_retry_status(self, attempt: int, review_config: Dict[str, Any]) -> None:
        """レビュー実行失敗時のリトライ状況を表示"""
        if attempt >= review_config["max_attempts"]:
            return

        print(
            f"[✖] review attempt {attempt}/{review_config['max_attempts']} failed, "
            f"retrying in {review_config['wait_seconds']}s...",
            file=sys.stderr,
        )

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

    def _execute_cc_sdd(
        self,
        plugin: Plugin,
        request: str,
        *,
        extra_args: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        provider_context: Optional[ProviderContext] = None,
    ) -> CommandResult:
        """cc-sddコマンドを実行

        Args:
            plugin: ロードされたプラグイン
            request: 仕様書作成のリクエスト
            extra_args: 追加の引数
            timeout: 実行タイムアウト（秒）
            provider_context: 選択済みプロバイダ

        Returns:
            CommandResult: コマンド実行結果
        """
        if provider_context is None:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_MISSING_API_KEY.value,
                    message="プロバイダが選択されていません。",
                    recoverable=False,
                )
            )

        executor = CommandExecutor(timeout=timeout or plugin.bridge.timeout)
        guard = PluginGuard()
        bridge = BridgeAdapter(
            guard=guard,
            executor=executor,
        )
        args = [request]
        if extra_args:
            args.extend(extra_args)

        # 非同期実行
        return asyncio.run(
            bridge.invoke(
                plugin.bridge.command,
                args,
                provider_context,
            )
        )

    def _has_logging_destination(self, logger: logging.Logger) -> bool:
        """ログ出力先が設定されているかを判定する"""
        if logger.handlers:
            return True
        return logger.hasHandlers()

    def _select_provider(self, options: Dict[str, Any]) -> ProviderContext:
        """ProviderSelectorがあればそれを使い、なければConfigから組み立てる"""
        provider_flag = options.get("provider")
        if self.provider_selector:
            return self.provider_selector.select(provider_flag)

        if provider_flag and provider_flag.lower() not in SUPPORTED_PROVIDERS:
            raise MagiException(
                MagiError(
                    code=ErrorCode.CONFIG_INVALID_VALUE.value,
                    message=f"Unknown provider '{provider_flag}'.",
                    details={"provider": provider_flag},
                    recoverable=False,
                )
            )

        target = (provider_flag or DEFAULT_PROVIDER_ID).lower()
        return ProviderContext(
            provider_id=target,
            api_key=self.config.api_key,
            model=self.config.model,
            endpoint=None,
            options={},
            used_default=provider_flag is None,
        )

    def _build_llm_client(
        self,
        provider: ProviderContext,
        *,
        concurrency_controller: Optional[ConcurrencyController] = None,
    ):
        """選択されたプロバイダに応じたLLMクライアント/アダプタを構築する"""
        if self.provider_factory:
            return self.provider_factory.build(provider)
        return LLMClient(
            api_key=provider.api_key,
            model=provider.model,
            retry_count=self.config.retry_count,
            timeout=self.config.timeout,
            concurrency_controller=concurrency_controller,
        )

    def _print_provider_selection(self, provider: ProviderContext) -> None:
        """選択されたプロバイダをstderrに明示する"""
        origin = "default" if provider.used_default else "flag"
        print(
            f"[provider] using {provider.provider_id} ({origin}) model={provider.model}",
            file=sys.stderr,
        )

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
