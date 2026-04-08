"""
環境変数の読み込みに関するユニットテスト

このモジュールでは、dotenv を使用した .env ファイルからの環境変数読み込みが
正しく機能し、OSの環境変数として利用可能になることを検証します。
"""
import os
import unittest
import tempfile
from unittest.mock import patch
from dotenv import load_dotenv

class TestEnvLoading(unittest.TestCase):
    """環境変数の読み込み機能を検証するテストクラス"""

    def test_env_variables_available_after_load_dotenv(self):
        """load_dotenv() 呼び出し後に .env の変数が利用可能であることを確認"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            with open(env_path, "w") as f:
                f.write("TEST_VAR_MAGI=magi_value\n")
            
            # 元の環境変数を保存し、テスト対象の変数を確実にクリアする
            original_val = os.environ.get("TEST_VAR_MAGI")
            os.environ.pop("TEST_VAR_MAGI", None)
            
            try:
                # .env をロード (既存の環境変数を上書きする場合は override=True が必要だが、
                # ここでは pop しているのでデフォルトの挙動でロードされる)
                load_dotenv(env_path)
                
                self.assertEqual(os.environ.get("TEST_VAR_MAGI"), "magi_value")
            finally:
                # クリーンアップ
                os.environ.pop("TEST_VAR_MAGI", None)
                if original_val is not None:
                    os.environ["TEST_VAR_MAGI"] = original_val

    def test_main_loads_dotenv(self):
        """__main__.main() 呼び出し時に load_dotenv() が実行されることを確認"""
        import io
        from magi.__main__ import main
        
        # load_dotenv をパッチして、呼ばれたかどうかを確認する
        with patch("magi.__main__.load_dotenv") as mock_load_dotenv:
            with patch("sys.stdout", new=io.StringIO()):
                main(["--version"])
            
            mock_load_dotenv.assert_called_once()

if __name__ == "__main__":
    unittest.main()
