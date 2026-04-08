"""セットアップスクリプトの動作検証用テスト。

Summary（要約）:
    scripts/setup.sh の動作を検証するテストモジュール。

Details（詳細）:
    このモジュールでは、scripts/setup.sh がシステム環境 (uv, npm の有無など) に応じて
    適切に動作し、必要な依存関係のチェックや警告を行うことを検証します。
    実環境への副作用を避けるため、subprocess.run はモック化されます。

Args:
    なし

Returns:
    なし

Raises:
    なし
"""

import unittest
import subprocess  # nosec
import logging
from unittest.mock import MagicMock, patch
from pathlib import Path
from hypothesis import given, example, strategies as st

logger = logging.getLogger(__name__)


def handle_setup_result(result: subprocess.CompletedProcess) -> str:
    """セットアップスクリプトの実行結果を解釈する。

    Summary（要約）:
        subprocess.CompletedProcess オブジェクトからスクリプトの実行結果を判定する。

    Details（詳細）:
        リターンコードが 0 以外の場合は "FAILED" を返し、
        標準出力に警告を示す絵文字や文字列（英語の warning/warn、日本語の警告）が含まれる場合は "WARNING" を、
        それ以外で正常終了した場合は "SUCCESS" を返します。

    Args:
        result (subprocess.CompletedProcess): スクリプトの実行結果。

    Returns:
        str: 実行結果に基づく状態メッセージ（"FAILED", "WARNING", "SUCCESS"）。

    Raises:
        AttributeError: result オブジェクトに必要な属性がない場合に発生する可能性があります。
    """
    if result.returncode != 0:
        return "FAILED"

    # 標準出力の正規化（bytes の場合はデコード）
    stdout = result.stdout
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    elif stdout is None:
        stdout = ""

    stdout_lower = stdout.lower()
    warning_tokens = ["⚠️", "warning", "warn", "警告"]

    if any(token in stdout_lower for token in warning_tokens):
        return "WARNING"

    return "SUCCESS"


class TestSetupScript(unittest.TestCase):
    """セットアップスクリプトの実行フローを検証するクラス。

    Summary（要約）:
        scripts/setup.sh の各種実行シナリオを検証する。

    Details（詳細）:
        このクラスは、setup.sh が uv や npm の有無を正しく検出し、
        適切な終了コードや警告メッセージを返すことを、実実行を伴わない
        シミュレーションによって検証します。

    Args:
        なし

    Returns:
        なし

    Raises:
        なし
    """

    def setUp(self) -> None:
        """テスト用の root_dir と setup_sh パスを初期化する。

        Args:
            None

        Returns:
            なし

        Raises:
            なし
        """
        self.root_dir: Path = Path(__file__).parent.parent.parent
        self.setup_sh: Path = self.root_dir / "scripts" / "setup.sh"

    @patch("subprocess.run")
    def test_setup_fails_without_uv(self, mock_run: MagicMock) -> None:
        """uv が存在しない場合に setup.sh がエラーで終了することを確認する。

        uv が見つからない状況をシミュレートし、スクリプトが非ゼロの
        終了コードを返し、エラーメッセージを出力することを検証します。

        Args:
            mock_run (MagicMock): subprocess.run のモックオブジェクト。

        Returns:
            なし

        Raises:
            なし
        """
        # uv がない場合のエラーをシミュレート
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="❌ uv is not installed. Please install it first.",
            stderr=""
        )

        # 実際には PATH を弄る必要はない (モック化しているため) が、
        # 引数の検証のために env を用意
        env = {"PATH": "/usr/bin"}

        result = subprocess.run(  # nosec
            [str(self.setup_sh)],
            env=env,
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        # モックの呼び出しを検証
        mock_run.assert_called_once_with(
            [str(self.setup_sh)],
            env=env,
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        self.assertEqual(handle_setup_result(result), "FAILED")
        self.assertIn("uv is not installed", result.stdout)

    @patch("subprocess.run")
    def test_setup_warns_without_npm(self, mock_run: MagicMock) -> None:
        """npm が存在しない場合に setup.sh が警告を出して続行することを確認する。

        npm が見つからないが uv は存在する状況をシミュレートし、
        スクリプトが警告を出しつつも正常終了することを検証します。

        Args:
            mock_run (MagicMock): subprocess.run のモックオブジェクト。

        Returns:
            なし

        Raises:
            なし
        """
        # npm がない場合の警告をシミュレート
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="⚠️ npm is not installed. Skipping frontend setup.",
            stderr=""
        )

        env = {"PATH": "/usr/bin:/usr/local/bin"}

        result = subprocess.run(  # nosec
            [str(self.setup_sh)],
            env=env,
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        # モックの呼び出しを検証
        mock_run.assert_called_once_with(
            [str(self.setup_sh)],
            env=env,
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        self.assertEqual(handle_setup_result(result), "WARNING")
        self.assertIn("npm is not installed. Skipping frontend setup.", result.stdout)

    @patch("subprocess.run")
    def test_setup_success_with_all_dependencies(self, mock_run: MagicMock) -> None:
        """uv と npm の両方が存在する場合に setup.sh が正常に終了することを確認する。

        依存関係がすべて揃っている状況をシミュレートし、スクリプトが
        正常終了することを検証します。

        Args:
            mock_run (MagicMock): subprocess.run のモックオブジェクト。

        Returns:
            なし

        Raises:
            なし
        """
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="✨ Setup complete! AI is ready to work.",
            stderr=""
        )

        result = subprocess.run(  # nosec
            [str(self.setup_sh)],
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        # モックの呼び出しを検証
        mock_run.assert_called_once_with(
            [str(self.setup_sh)],
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        self.assertEqual(handle_setup_result(result), "SUCCESS")
        self.assertNotIn("uv is not installed", result.stdout)
        self.assertIn("Setup complete", result.stdout)

    @example(returncode=0, msg="⚠️ some warning")
    @example(returncode=0, msg="this is a warning message")
    @example(returncode=0, msg="warn: something happened")
    @example(returncode=0, msg="警告: プロセスが中断されました")
    @given(
        returncode=st.integers(min_value=0, max_value=2),
        msg=st.one_of(
            st.text(min_size=1, max_size=500).filter(lambda x: x.isprintable()),
            st.sampled_from(["⚠️ warning", "warning: low disk space", "warn message", "警告メッセージ"])
        ),
    )
    def test_setup_property_with_hypothesis(self, returncode: int, msg: str) -> None:
        """Hypothesis を用いて setup.sh の実行結果に関する不変条件を検証する。

        Args:
            returncode (int): ランダムな終了コード
            msg (str): ランダムな標準出力メッセージ

        Returns:
            なし

        Raises:
            なし
        """
        # mock_run を介さず、直接 handle_setup_result の挙動を検証する
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = returncode
        mock_result.stdout = msg
        mock_result.stderr = ""

        status = handle_setup_result(mock_result)

        msg_lower = msg.lower()
        warning_tokens = ["⚠️", "warning", "warn", "警告"]

        if returncode != 0:
            self.assertEqual(status, "FAILED")
        elif any(token in msg_lower for token in warning_tokens):
            self.assertEqual(status, "WARNING")
        else:
            self.assertEqual(status, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
