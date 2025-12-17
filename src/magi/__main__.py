"""MAGIシステムのCLIエントリーポイント"""

import json
import sys
from typing import List

from magi import __version__
from magi.cli.parser import ArgumentParser
from magi.cli.main import MagiCLI
from magi.config.manager import Config, ConfigManager
from magi.config.provider import ProviderConfigLoader
from magi.core.providers import ProviderAdapterFactory, ProviderRegistry, ProviderSelector
from magi.errors import MagiException


def main(args: List[str] | None = None) -> int:
    """
    MAGIシステムのメインエントリーポイント

    Args:
        args: コマンドライン引数（Noneの場合はsys.argvを使用）

    Returns:
        終了コード（0: 成功、非0: エラー）
    """
    if args is None:
        args = sys.argv[1:]

    # 引数解析
    parser = ArgumentParser()
    parsed = parser.parse(args)

    # バージョン表示
    if parsed.options.get("version"):
        print(f"magi {__version__}")
        return 0

    # ヘルプ表示
    if parsed.options.get("help") or (not parsed.command and not args):
        _print_help()
        return 0

    # バリデーション
    validation = parser.validate(parsed)
    if not validation.is_valid:
        for error in validation.errors:
            print(error, file=sys.stderr)
        return 1

    if parsed.options.get("config_check"):
        try:
            config = ConfigManager().load()
        except MagiException as exc:
            print(f"Configuration error: {exc.error.message}", file=sys.stderr)
            return 1
        print(json.dumps(config.dump_masked(), ensure_ascii=False, indent=2))
        return 0

    # プロバイダ設定の読み込み
    provider_selector = None
    provider_factory = ProviderAdapterFactory()
    try:
        provider_configs = ProviderConfigLoader().load()
        registry = ProviderRegistry(provider_configs)
        provider_selector = ProviderSelector(
            registry,
            default_provider=provider_configs.default_provider,
        )
    except MagiException as exc:
        if parsed.command not in ("help", "version"):
            print(f"Provider configuration error: {exc.error.message}", file=sys.stderr)
            return 1

    # 設定読み込み
    try:
        config_manager = ConfigManager()
        config = config_manager.load()
    except MagiException as exc:
        # API keyがなくてもヘルプ系コマンドは動作させる
        if parsed.command in ("help", "version"):
            config = Config(api_key="")
        elif provider_selector is not None:
            try:
                provider_ctx = provider_selector.select(parsed.options.get("provider"))
            except MagiException as exc:
                print(f"Provider selection error: {exc.error.message}", file=sys.stderr)
                return 1
            config = Config(api_key=provider_ctx.api_key, model=provider_ctx.model)
        else:
            print(f"Configuration error: {exc.error.message}", file=sys.stderr)
            return 1
    except Exception as e:
        # 予期しないエラーの場合
        if parsed.command in ("help", "version"):
            config = Config(api_key="")
        else:
            print(f"Configuration error: {e}", file=sys.stderr)
            return 1

    # CLI実行
    cli = MagiCLI(
        config,
        output_format=parsed.output_format,
        plugin=parsed.plugin,
        provider_selector=provider_selector,
        provider_factory=provider_factory,
    )
    return cli.run(parsed.command, parsed.args, options=parsed.options)


def _print_help() -> None:
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
    --config-check       設定内容を検証して表示（API keyはマスク）
    --format <format>    出力形式を指定（json, markdown）
    --plugin <name>      使用するプラグインを指定

Examples:
    magi ask "このコードをレビューしてください"
    magi spec "ログイン機能の仕様書を作成"
    magi --format json ask "リファクタリングの提案"

詳細は https://github.com/yohi/magi-core を参照してください。
"""
    print(help_text)


if __name__ == "__main__":
    sys.exit(main())
