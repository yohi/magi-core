"""
MagiCLIメインモジュール

MAGIシステムのエントリーポイントとコマンドハンドラーの統合
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import yaml
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional

from magi import __version__
from magi.cli.model_fetcher import fetch_available_models
from magi.cli.parser import ArgumentParser, ParsedCommand, VALID_COMMANDS
from magi.config.manager import Config
from magi.config.provider import (
    AUTH_BASED_PROVIDERS,
    DEFAULT_PROVIDER_ID,
    SUPPORTED_PROVIDERS,
    RECOMMENDED_MODELS,
    ProviderConfig,
    ProviderConfigLoader,
)
from magi.core.concurrency import ConcurrencyController
from magi.core.consensus import ConsensusEngine
from magi.core.providers import (
    ProviderAdapterFactory,
    ProviderContext,
    ProviderSelector,
)
from magi.errors import MagiError, MagiException, ErrorCode
from magi.llm.auth import AuthContext, get_auth_provider, TokenManager
from magi.llm.client import LLMClient
from magi.output.formatter import OutputFormat, OutputFormatter
from magi.plugins.bridge import BridgeAdapter
from magi.plugins.executor import CommandExecutor, CommandResult
from magi.plugins.guard import PluginGuard

if TYPE_CHECKING:
    from magi.plugins.loader import Plugin

API_KEY_PROVIDERS = ("openai", "anthropic", "gemini", "google")


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

    def run(
        self, command: str, args: List[str], options: Dict[str, Any] | None = None
    ) -> int:
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
                file=sys.stderr,
            )
            return 1

        # askコマンド
        if command == "ask":
            return self._run_ask_command(args, options)

        # specコマンド
        if command == "spec":
            return self._run_spec_command(args, options)

        # authコマンド
        if command == "auth":
            return self._run_auth_command(args, options)

        # initコマンド
        if command == "init":
            return self._run_init_command(args, options)

        # 未実装のコマンド
        print(f"Command '{command}' is not yet implemented.", file=sys.stderr)
        return 1

    def _run_auth_command(
        self,
        args: List[str],
        options: Optional[Dict[str, Any]] = None,
    ) -> int:
        """authコマンドの実行

        Args:
            args: コマンド引数
            options: オプション

        Returns:
            int: 終了コード
        """
        if not args:
            print("Usage: magi auth <subcommand> [provider]", file=sys.stderr)
            print("Subcommands: login, logout, status", file=sys.stderr)
            return 1

        subcommand = args[0]
        provider_id = args[1] if len(args) > 1 else None

        if subcommand == "login":
            return asyncio.run(self._auth_login(provider_id))
        elif subcommand == "logout":
            return self._auth_logout(provider_id)
        elif subcommand == "status":
            return asyncio.run(self._auth_status(provider_id))
        else:
            print(f"Unknown subcommand: {subcommand}", file=sys.stderr)
            return 1

    async def _auth_login(self, provider_id: Optional[str]) -> int:
        """プロバイダへのログイン（認証フロー実行）"""
        if not provider_id:
            if not sys.stdin.isatty():
                provider_id = os.environ.get("MAGI_PROVIDER_ID")
                if not provider_id:
                    print(
                        "Error: No provider specified and MAGI_PROVIDER_ID not set in non-interactive mode.",
                        file=sys.stderr,
                    )
                    return 1
            else:
                # プロバイダが未指定の場合、対話的に選択させる
                candidates = sorted(list(AUTH_BASED_PROVIDERS))
                print("Select a provider to login:", file=sys.stderr)
                for i, p in enumerate(candidates, 1):
                    print(f"  {i}) {p}", file=sys.stderr)

                try:
                    # ユーザー入力を待機
                    choice = input("Enter number: ").strip()
                    if not choice:
                        print("Canceled.", file=sys.stderr)
                        return 1

                    idx = int(choice) - 1
                    if 0 <= idx < len(candidates):
                        provider_id = candidates[idx]
                    else:
                        print("Invalid selection.", file=sys.stderr)
                        return 1
                except (ValueError, IndexError):
                    print("Invalid input.", file=sys.stderr)
                    return 1
                except (KeyboardInterrupt, EOFError):
                    print("\nCanceled.", file=sys.stderr)
                    return 1

        provider_id = provider_id.lower()
        print(f"Authenticating with {provider_id}...", file=sys.stderr)

        try:
            # プロバイダ設定をロード（APIキーの有無に関わらず設定自体を取得したい）
            # authコマンド実行時は、他のプロバイダ設定が不完全でも許容するためバリデーションをスキップ
            loader = ProviderConfigLoader()
            configs = loader.load(skip_validation=True)

            provider_config = configs.providers.get(provider_id)
            if not provider_config:
                # 設定がない場合、デフォルト設定で試行する
                # (設定ファイルに記述がなくても、コード内のデフォルト値で認証できる可能性があるため)
                print(
                    f"Warning: Configuration for '{provider_id}' not found. Using defaults.",
                    file=sys.stderr,
                )
                provider_config = ProviderConfig(provider_id=provider_id, options={})

            # AuthContextの構築
            auth_context = self._build_auth_context(provider_config.options)

            # 必須パラメータの対話的入力（設定ファイルにない場合）
            if provider_id == "antigravity":
                # Check for non-interactive environment
                if not sys.stdin.isatty():
                    # Attempt to get from env vars or fail
                    if not auth_context.client_id:
                        auth_context.client_id = (
                            os.environ.get("MAGI_ANTIGRAVITY_CLIENT_ID") or ""
                        )
                    if not auth_context.client_secret:
                        auth_context.client_secret = (
                            os.environ.get("MAGI_ANTIGRAVITY_CLIENT_SECRET") or ""
                        )

                    if not auth_context.client_id or not auth_context.client_secret:
                        raise RuntimeError(
                            "Non-interactive environment detected. "
                            "Please set MAGI_ANTIGRAVITY_CLIENT_ID and MAGI_ANTIGRAVITY_CLIENT_SECRET environment variables, "
                            "or configure them in magi.yaml."
                        )
                else:
                    # Interactive input
                    if not auth_context.client_id:
                        val = input("Antigravity Client ID: ").strip()
                        if val:
                            auth_context.client_id = val
                    if not auth_context.client_secret:
                        from getpass import getpass

                        val = getpass("Antigravity Client Secret: ").strip()
                        if val:
                            auth_context.client_secret = val

                if not auth_context.token_url:
                    default_url = "https://oauth2.googleapis.com/token"
                    if not sys.stdin.isatty():
                        # Non-interactive: check env var or use default
                        val = os.environ.get("MAGI_ANTIGRAVITY_TOKEN_URL")
                        auth_context.token_url = val if val else default_url
                    else:
                        # Interactive input
                        val = input(
                            f"Antigravity Token URL [default: {default_url}]: "
                        ).strip()
                        auth_context.token_url = val if val else default_url

            # AuthProviderの取得と認証実行
            auth_provider = get_auth_provider(provider_id, auth_context)
            await auth_provider.authenticate()

            print(f"Successfully authenticated with {provider_id}.", file=sys.stderr)
            return 0

        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Authentication failed: {e}", file=sys.stderr)
            return 1

    def _auth_logout(self, provider_id: Optional[str]) -> int:
        """プロバイダからのログアウト（トークン削除）"""
        if not provider_id:
            print("Error: provider argument is required for logout.", file=sys.stderr)
            print("Usage: magi auth logout <provider>", file=sys.stderr)
            return 1

        provider_id = provider_id.lower()

        if provider_id not in AUTH_BASED_PROVIDERS:
            print(
                f"Error: '{provider_id}' is not a valid authentication provider.",
                file=sys.stderr,
            )
            print(
                f"Available providers: {', '.join(sorted(AUTH_BASED_PROVIDERS))}",
                file=sys.stderr,
            )
            return 1

        service_name = f"magi.{provider_id}"

        try:
            token_manager = TokenManager()
            token_manager.delete_token(service_name)
            print(f"Logged out from {provider_id}.", file=sys.stderr)
            return 0
        except Exception as e:
            print(f"Logout failed: {e}", file=sys.stderr)
            return 1

    async def _auth_status(self, provider_id: Optional[str]) -> int:
        """認証ステータスの表示"""
        providers = (
            [provider_id.lower()] if provider_id else sorted(list(AUTH_BASED_PROVIDERS))
        )

        token_manager = TokenManager()

        print("Authentication Status:")
        print("-" * 40)

        found_any = False
        for pid in providers:
            service_name = f"magi.{pid}"
            token = token_manager.get_token(service_name)

            if token:
                status = "Authenticated"
                # AntigravityやClaude等はトークン内に有効期限情報を含んでいる場合があるが、
                # ここでは単純にトークンの存在有無で判定する。
                # 必要であれば AuthProvider.get_token(force_refresh=False) を呼んで検証することも可能だが、
                # 副作用（リフレッシュ等）を避けるため簡易チェックに留める。
                print(f"{pid:<15}: \033[32m{status}\033[0m")
                found_any = True
            else:
                if provider_id:  # 指定されたプロバイダが見つからない場合のみ表示
                    print(f"{pid:<15}: Not authenticated")

        if not found_any and not provider_id:
            print("No active sessions found.")

        return 0

    def _build_auth_context(self, options: Dict[str, Any]) -> AuthContext:
        """オプションからAuthContextを生成する"""
        scopes = options.get("scopes")
        scope_list: List[str] = []
        if isinstance(scopes, str):
            scope_list = [s for s in scopes.split() if s]
        elif isinstance(scopes, list):
            scope_list = [str(item) for item in scopes]

        extras = options.get("extras")
        extras_dict: Dict[str, str] = {}
        if isinstance(extras, dict):
            for k, v in extras.items():
                extras_dict[str(k)] = str(v)

        return AuthContext(
            client_id=options.get("client_id"),
            client_secret=options.get("client_secret"),
            scopes=scope_list,
            auth_url=options.get("auth_url"),
            token_url=options.get("token_url"),
            redirect_uri=options.get("redirect_uri"),
            audience=options.get("audience"),
            extras=extras_dict,
        )

    def _run_init_command(
        self,
        args: List[str],
        options: Optional[Dict[str, Any]] = None,
    ) -> int:
        """initコマンドの実行: 設定ファイルの生成 (対話的)"""
        target_path = Path.cwd() / "magi.yaml"

        if target_path.exists():
            force = (options or {}).get("force")
            if force:
                pass
            elif not sys.stdin.isatty():
                print(
                    f"Error: '{target_path}' already exists and --force not specified in non-interactive mode.",
                    file=sys.stderr,
                )
                return 1
            else:
                print(f"Warning: '{target_path}' already exists.", file=sys.stderr)
                try:
                    choice = input("Overwrite? [y/N]: ").strip().lower()
                    if choice not in ("y", "yes"):
                        print("Aborted.", file=sys.stderr)
                        return 0
                except (KeyboardInterrupt, EOFError):
                    print("\nAborted.", file=sys.stderr)
                    return 1

        try:
            print("Select default LLM provider:")
            providers = sorted(list(SUPPORTED_PROVIDERS))
            for i, p in enumerate(providers, 1):
                print(f"  {i}) {p}")

            p_choice = input(f"Choose provider [1-{len(providers)}]: ").strip()
            if not p_choice:
                selected_provider = DEFAULT_PROVIDER_ID
            else:
                try:
                    idx = int(p_choice) - 1
                    if 0 <= idx < len(providers):
                        selected_provider = providers[idx]
                    else:
                        print(f"Invalid selection. Using '{DEFAULT_PROVIDER_ID}'.")
                        selected_provider = DEFAULT_PROVIDER_ID
                except ValueError:
                    print(f"Invalid input. Using '{DEFAULT_PROVIDER_ID}'.")
                    selected_provider = DEFAULT_PROVIDER_ID

            api_key = ""
            fetched_models = []
            if selected_provider in API_KEY_PROVIDERS:
                api_key = input(
                    f"Enter API Key for {selected_provider} (optional, leave empty to skip fetching models): "
                ).strip()
                if api_key:
                    print("Fetching available models...")
                    # gemini は google プロバイダーのロジックを使用する
                    fetch_id = (
                        "google" if selected_provider == "gemini" else selected_provider
                    )
                    fetched_models = fetch_available_models(fetch_id, api_key)
            elif selected_provider == "antigravity":
                # Antigravityの場合は Client ID/Secret が必要になるため、トークンリフレッシュも含めて AuthProvider を使用する
                client_id = ""
                client_secret = ""
                token_url = "https://oauth2.googleapis.com/token"

                # Check for non-interactive environment
                if not sys.stdin.isatty():
                    client_id = os.environ.get("MAGI_ANTIGRAVITY_CLIENT_ID") or ""
                    client_secret = (
                        os.environ.get("MAGI_ANTIGRAVITY_CLIENT_SECRET") or ""
                    )
                    token_url = (
                        os.environ.get("MAGI_ANTIGRAVITY_TOKEN_URL") or token_url
                    )
                else:
                    # Interactive input
                    print(
                        "Antigravity configuration (optional if already logged in with magi auth):"
                    )
                    client_id = input("Antigravity Client ID: ").strip()
                    if client_id:
                        from getpass import getpass

                        client_secret = getpass("Antigravity Client Secret: ").strip()

                    token_url_input = input(
                        f"Antigravity Token URL [default: {token_url}]: "
                    ).strip()
                    if token_url_input:
                        token_url = token_url_input

                # AuthContextの構築
                auth_context = AuthContext(
                    client_id=client_id,
                    client_secret=client_secret,
                    token_url=token_url,
                    scopes=[],  # デフォルトスコープが使用される
                    extras={},
                )

                try:
                    # AuthProviderの取得
                    # ここでトークンを取得・リフレッシュを試みる
                    auth_provider = get_auth_provider(selected_provider, auth_context)
                    # 非同期メソッドを同期的に実行
                    token = asyncio.run(auth_provider.get_token())

                    print("Fetching available models...")
                    fetched_models = fetch_available_models(selected_provider, token)
                except Exception as e:
                    print(
                        f"Warning: Failed to authenticate with {selected_provider}: {e}",
                        file=sys.stderr,
                    )
                    print(
                        "Using default models. Run 'magi auth login antigravity' to fix authentication.",
                        file=sys.stderr,
                    )

            elif selected_provider in AUTH_BASED_PROVIDERS:
                token_manager = TokenManager()
                token_data = token_manager.get_token(f"magi.{selected_provider}")
                if token_data:
                    token = token_data
                    try:
                        payload = json.loads(token_data)
                        if isinstance(payload, dict) and "access_token" in payload:
                            token = payload["access_token"]
                    except json.JSONDecodeError:
                        pass

                    print("Fetching available models...")
                    fetched_models = fetch_available_models(selected_provider, token)
                else:
                    print(
                        f"Note: Not authenticated with {selected_provider}. Using default models. "
                        f"Run 'magi auth login {selected_provider}' to fetch dynamic models.",
                        file=sys.stderr,
                    )

            models = (
                fetched_models
                if fetched_models
                else RECOMMENDED_MODELS.get(selected_provider, [])
            )
            selected_model = ""
            if models:
                print(f"Select model for {selected_provider}:")
                for i, m in enumerate(models, 1):
                    print(f"  {i}) {m}")
                print(f"  {len(models) + 1}) Enter custom model")

                m_choice = input(f"Choose model [1-{len(models) + 1}]: ").strip()
                if not m_choice:
                    selected_model = models[0]
                else:
                    try:
                        idx = int(m_choice) - 1
                        if 0 <= idx < len(models):
                            selected_model = models[idx]
                        elif idx == len(models):
                            selected_model = input("Enter custom model name: ").strip()
                            if not selected_model:
                                selected_model = models[0]
                        else:
                            print(f"Invalid selection. Using '{models[0]}'.")
                            selected_model = models[0]
                    except ValueError:
                        print(f"Invalid input. Using '{models[0]}'.")
                        selected_model = models[0]
            else:
                while True:
                    selected_model = input(
                        f"Enter model name for {selected_provider}: "
                    ).strip()
                    if selected_model:
                        break
                    print("Model name cannot be empty. Please try again.")

            if not api_key and selected_provider not in AUTH_BASED_PROVIDERS:
                api_key = input(
                    f"Enter API Key for {selected_provider} (optional): "
                ).strip()

            config_dict: Dict[str, Any] = {
                "default_provider": selected_provider,
                "providers": {selected_provider: {"model": selected_model}},
                "debate_rounds": 1,
                "voting_threshold": "majority",
                "output_format": "markdown",
                "timeout": 60,
            }
            if api_key:
                config_dict["providers"][selected_provider]["api_key"] = api_key
            elif selected_provider == "antigravity":
                if "options" not in config_dict["providers"][selected_provider]:
                    config_dict["providers"][selected_provider]["options"] = {}

                if client_id:
                    config_dict["providers"][selected_provider]["options"][
                        "client_id"
                    ] = client_id
                if client_secret:
                    config_dict["providers"][selected_provider]["options"][
                        "client_secret"
                    ] = client_secret
                if token_url:
                    config_dict["providers"][selected_provider]["options"][
                        "token_url"
                    ] = token_url

            with open(target_path, "w", encoding="utf-8") as f:
                f.write("# magi.yaml\n")
                yaml.dump(
                    config_dict,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )

            has_secrets = False
            providers_cfg = config_dict.get("providers", {})
            if isinstance(providers_cfg, dict):
                for provider_name, provider_cfg in providers_cfg.items():
                    if isinstance(provider_cfg, dict):
                        for key in provider_cfg.keys():
                            k_lower = key.lower()
                            if (
                                ("api" in k_lower and "key" in k_lower)
                                or "secret" in k_lower
                                or "token" in k_lower
                            ):
                                has_secrets = True
                                break

                        if not has_secrets and provider_name == "antigravity":
                            options = provider_cfg.get("options", {})
                            if isinstance(options, dict) and "client_secret" in options:
                                has_secrets = True

                    if has_secrets:
                        break

            if has_secrets:
                try:
                    os.chmod(target_path, 0o600)
                except Exception:
                    # Handle platforms where chmod might fail or behave differently (e.g. Windows)
                    pass

            print(f"Successfully created '{target_path}'.", file=sys.stderr)
            return 0
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error during initialization: {e}", file=sys.stderr)
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

    def _run_spec_command(
        self, args: List[str], options: Optional[Dict[str, Any]] = None
    ) -> int:
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
            print(
                "Please ensure the plugin exists in the plugins directory.",
                file=sys.stderr,
            )
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
                print(
                    "cc-sdd command is not available. Please install it first:",
                    file=sys.stderr,
                )
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
            print(
                f"cc-sdd command failed with exit code {result.return_code}",
                file=sys.stderr,
            )
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
        print(
            f"Agent overrides loaded for personas: {', '.join(p.name for p in plugin.agent_overrides.keys())}"
        )

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
                last_errors.append(
                    "レビュー実行がグローバルタイムアウトを超過しました。"
                )
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
                last_errors.append(
                    exc.error.message if hasattr(exc, "error") else str(exc)
                )
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

            spec_text, parsed_reviews, parse_errors = self._parse_review_output(
                result.stdout
            )
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

    def _split_spec_args(
        self, args: List[str], options: Dict[str, Any]
    ) -> tuple[bool, List[str]]:
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

        spec_text = (
            payload.get("spec") if isinstance(payload.get("spec"), str) else None
        )
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
                errors.append(
                    f"{entry.get('reviewer_id', 'unknown')} のscoreが数値ではありません。"
                )
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
        self,
        spec_text: Optional[str],
        reviews: List[Dict[str, Any]],
        review_config: Dict[str, Any],
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
            icon = (
                "✔"
                if status in success_statuses
                else "✖"
                if status in failure_statuses
                else "…"
            )
            if status in success_statuses:
                completed += 1
            score = entry["score"]
            message = entry["message"]
            reviewer_id = entry["reviewer_id"]
            print(f'[{icon}] {reviewer_id} {score:.2f} "{message}" ({status})')

        if reviews:
            print(
                "[…] overall "
                f"{completed}/{len(reviews)} complete "
                f"(max_attempts={review_config['max_attempts']}, "
                f"wait={review_config['wait_seconds']}s, "
                f"per_attempt_timeout={review_config['per_attempt_timeout']}s, "
                f"global_timeout={review_config['global_timeout']}s)"
            )

    def _print_review_retry_status(
        self, attempt: int, review_config: Dict[str, Any]
    ) -> None:
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
            Path(__file__).parent.parent.parent.parent
            / "plugins"
            / plugin_name
            / "plugin.yaml",
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
            return self.provider_factory.build(
                provider, concurrency_controller=concurrency_controller
            )
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

    def _extract_fail_safe_summary(
        self, engine: ConsensusEngine
    ) -> Optional[Dict[str, Any]]:
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
    auth             認証管理 (login, logout, status)
    init             設定ファイル(magi.yaml)を生成

Options:
    -h, --help           ヘルプメッセージを表示
    -v, --version        バージョン情報を表示
    --format <format>    出力形式を指定（json, markdown）
    --plugin <name>      使用するプラグインを指定

Examples:
    magi ask "このコードをレビューしてください"
    magi spec "ログイン機能の仕様書を作成"
    magi --format json ask "リファクタリングの提案"
    magi auth login antigravity

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
