"""MAGIシステムのCLIエントリーポイント"""

import sys
from typing import List

from magi import __version__


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

    # バージョン表示
    if "--version" in args or "-v" in args:
        print(f"magi {__version__}")
        return 0

    # ヘルプ表示
    if "--help" in args or "-h" in args or len(args) == 0:
        print_help()
        return 0

    # TODO: コマンド実行の実装
    # 現時点では未実装のため、エラーメッセージを表示
    print("MAGIシステムは現在開発中です。", file=sys.stderr)
    print("詳細は https://github.com/yohi/magi-core を参照してください。", file=sys.stderr)
    return 1


def print_help() -> None:
    """ヘルプメッセージを表示"""
    help_text = """MAGI System - 3賢者による合議プロセスを通じた多角的判断を提供するCLIツール

使用方法:
    magi <command> [args]

コマンド:
    <command>    実行するコマンド（実装予定）

オプション:
    -h, --help     このヘルプメッセージを表示
    -v, --version  バージョン情報を表示

詳細:
    MAGIシステムは、3つの異なる人格（MELCHIOR、BALTHASAR、CASPER）による
    合議プロセスを通じて、より多角的で信頼性の高い判断を提供します。

    詳細は https://github.com/yohi/magi-core を参照してください。
"""
    print(help_text)


if __name__ == "__main__":
    sys.exit(main())
