import os
import unittest
import tempfile
from dotenv import load_dotenv

class TestEnvLoading(unittest.TestCase):
    def test_env_variables_available_after_load_dotenv(self):
        """load_dotenv() 呼び出し後に .env の変数が利用可能であることを確認"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            with open(env_path, "w") as f:
                f.write("TEST_VAR_MAGI=magi_value\n")
            
            # 元の環境変数を保存
            original_val = os.environ.get("TEST_VAR_MAGI")
            
            try:
                # .env をロード
                load_dotenv(env_path)
                
                self.assertEqual(os.environ.get("TEST_VAR_MAGI"), "magi_value")
            finally:
                # クリーンアップ
                if "TEST_VAR_MAGI" in os.environ:
                    del os.environ["TEST_VAR_MAGI"]
                if original_val is not None:
                    os.environ["TEST_VAR_MAGI"] = original_val

if __name__ == "__main__":
    unittest.main()
