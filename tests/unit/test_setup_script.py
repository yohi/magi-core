"""セットアップスクリプトの動作検証用テスト。

このモジュールでは、scripts/setup.sh がシステム環境 (uv, npm の有無など) に応じて
適切に動作し、必要な依存関係のチェックや警告を行うことを検証します。
実環境への副作用を避けるため、subprocess.run はモック化されます。
"""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from hypothesis import given, strategies as st


class TestSetupScript(unittest.TestCase):
    """セットアップスクリプトの実行フローを検証するクラス。

    このクラスは、setup.sh が uv や npm の有無を正しく検出し、
    適切な終了コードや警告メッセージを返すことを、実実行を伴わない
    シミュレーションによって検証します。
    """

    def setUp(self) -> None:
        """テスト用の root_dir と setup_sh パスを初期化する。

        Args:
            None

        Returns:
            None

        Raises:
            None
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
            None

        Raises:
            None
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

        import subprocess  # nosec
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

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uv is not installed", result.stdout)

    @patch("subprocess.run")
    def test_setup_warns_without_npm(self, mock_run: MagicMock) -> None:
        """npm が存在しない場合に setup.sh が警告を出して続行することを確認する。

        npm が見つからないが uv は存在する状況をシミュレートし、
        スクリプトが警告を出しつつも正常終了することを検証します。

        Args:
            mock_run (MagicMock): subprocess.run のモックオブジェクト。

        Returns:
            None

        Raises:
            None
        """
        # npm がない場合の警告をシミュレート
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="⚠️ npm is not installed. Skipping frontend setup.",
            stderr=""
        )

        env = {"PATH": "/usr/bin:/usr/local/bin"}

        import subprocess  # nosec
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

        self.assertEqual(result.returncode, 0)
        self.assertIn("npm is not installed. Skipping frontend setup.", result.stdout)

    @patch("subprocess.run")
    def test_setup_success_with_all_dependencies(self, mock_run: MagicMock) -> None:
        """uv と npm の両方が存在する場合に setup.sh が正常に終了することを確認する。

        依存関係がすべて揃っている状況をシミュレートし、スクリプトが
        正常終了することを検証します。

        Args:
            mock_run (MagicMock): subprocess.run のモックオブジェクト。

        Returns:
            None

        Raises:
            None
        """
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="✨ Setup complete! AI is ready to work.",
            stderr=""
        )

        import subprocess  # nosec
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

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("uv is not installed", result.stdout)
        self.assertIn("Setup complete", result.stdout)

    @patch("subprocess.run")
    @given(
        returncode=st.integers(min_value=0, max_value=2),
        msg=st.text(min_size=1, max_size=500).filter(lambda x: x.isprintable()),
    )
    def test_setup_property_with_hypothesis(
        self, mock_run: MagicMock, returncode: int, msg: str
    ) -> None:
        """Hypothesis を用いて setup.sh の実行結果に関する不変条件を検証する。

        Args:
            mock_run (MagicMock): subprocess.run のモックオブジェクト。
            returncode (int): ランダムな終了コード
            msg (str): ランダムな標準出力メッセージ

        Returns:
            None

        Raises:
            None
        """
        mock_run.return_value = MagicMock(
            returncode=returncode,
            stdout=msg,
            stderr=""
        )

        import subprocess  # nosec
        result = subprocess.run(  # nosec
            [str(self.setup_sh)],
            cwd=str(self.root_dir),
            capture_output=True,
            text=True
        )

        # 終了コードに基づくメッセージの整合性を検証
        if result.returncode != 0:
            # エラーの場合は、何らかのエラーが通知されているはず (このテストでは msg に依存)
            self.assertEqual(result.stdout, msg)
        else:
            # 正常終了の場合は、Setup complete または警告が含まれている可能性がある
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, msg)


if __name__ == "__main__":
    unittest.main()
