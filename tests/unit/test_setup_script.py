"""
セットアップスクリプトの動作検証用テスト

scripts/setup.sh がシステム環境 (uv, npm の有無など) に応じて
適切に動作し、必要な依存関係のチェックや警告を行うことを確認します。
"""
import os
import subprocess
import unittest
import shutil
import tempfile
import stat
from pathlib import Path

class TestSetupScript(unittest.TestCase):
    """セットアップスクリプトの実行フローを検証するクラス"""

    def setUp(self) -> None:
        """テスト用の root_dir と setup_sh パスを初期化する"""
        self.root_dir: Path = Path(__file__).parent.parent.parent
        self.setup_sh: Path = self.root_dir / "scripts" / "setup.sh"

    def test_setup_fails_without_uv(self) -> None:
        """uv が存在しない場合に setup.sh がエラーで終了することを確認"""
        # PATH から uv を除外するために、必要最小限のツールのみを symlink したディレクトリを使用
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Link basic tools but NOT uv
            tools = ["bash", "sh", "ls", "grep", "cp", "touch", "mkdir", "chmod", "rm", "cat"]
            for tool in tools:
                path = shutil.which(tool)
                if path:
                    (tmpdir_path / tool).symlink_to(path)
            
            env = os.environ.copy()
            env["PATH"] = str(tmpdir_path)
            
            # 実行権限があるか確認し、なければ付与。テスト後に元の権限を復元する。
            original_mode = None
            if not os.access(self.setup_sh, os.X_OK):
                original_mode = os.stat(self.setup_sh).st_mode
                os.chmod(self.setup_sh, original_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            try:
                result = subprocess.run(
                    [str(self.setup_sh)],
                    env=env,
                    cwd=str(self.root_dir),
                    capture_output=True,
                    text=True
                )
                
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("uv is not installed", result.stdout + result.stderr)
            finally:
                if original_mode is not None:
                    os.chmod(self.setup_sh, original_mode)

    def test_setup_warns_without_npm(self):
        """npm が存在しない場合に setup.sh が警告を出して続行することを確認"""
        # PATH から npm を除外し、uv は残す
        uv_path = shutil.which("uv")
        if uv_path is None:
            self.skipTest("uv is required for this test")

        frontend_dir = self.root_dir / "frontend"
        frontend_created = False
        if not frontend_dir.exists():
            frontend_dir.mkdir(parents=True)
            frontend_created = True

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                # Link basic tools AND uv, but NOT npm
                tools = ["bash", "sh", "ls", "grep", "cp", "touch", "mkdir", "chmod", "rm", "cat", "uv"]
                for tool in tools:
                    path = shutil.which(tool)
                    if path:
                        (tmpdir_path / tool).symlink_to(path)
                
                env = os.environ.copy()
                env["PATH"] = str(tmpdir_path)
                
                result = subprocess.run(
                    [str(self.setup_sh)],
                    env=env,
                    cwd=str(self.root_dir),
                    capture_output=True,
                    text=True
                )
                
                # npm がないことによる警告は stdout または stderr に出るはず
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0)
                self.assertIn("npm is not installed. Skipping frontend setup.", output)
        finally:
            if frontend_created and frontend_dir.exists():
                shutil.rmtree(frontend_dir)

    def test_setup_success_with_all_dependencies(self) -> None:
        """uv と npm の両方が存在する場合に setup.sh が正常に終了することを確認"""
        uv_path = shutil.which("uv")
        npm_path = shutil.which("npm")
        if uv_path is None or npm_path is None:
            self.skipTest("Both uv and npm are required for this test")

        frontend_dir = self.root_dir / "frontend"
        frontend_created = False
        if not frontend_dir.exists():
            frontend_dir.mkdir(parents=True)
            frontend_created = True

        try:
            # 実行環境の PATH をそのまま使用
            result = subprocess.run(
                [str(self.setup_sh)],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True
            )
            
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("uv is not installed", result.stdout + result.stderr)
        finally:
            if frontend_created and frontend_dir.exists():
                shutil.rmtree(frontend_dir)

if __name__ == "__main__":
    unittest.main()
