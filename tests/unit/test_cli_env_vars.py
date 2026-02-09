import os
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from magi.cli.main import MagiCLI
from magi.config.manager import Config
from magi.llm.auth import AuthContext


class TestMagiCLIEnvVars(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.cli = MagiCLI(config=self.config)

    @patch("magi.cli.main.ProviderConfigLoader")
    @patch("magi.cli.main.get_auth_provider")
    @patch("magi.cli.main.sys.stdin.isatty", return_value=False)
    def test_auth_login_non_interactive_antigravity_env_vars(
        self, mock_isatty, mock_get_auth, mock_loader
    ):
        """非対話モードで ANTIGRAVITY_CLIENT_ID 等の環境変数が読み込まれることを確認"""
        
        mock_loader.return_value.load.return_value.providers = {}
        mock_auth_provider = MagicMock()
        mock_get_auth.return_value = mock_auth_provider

        # 環境変数をセット
        env_vars = {
            "ANTIGRAVITY_CLIENT_ID": "env_client_id",
            "ANTIGRAVITY_CLIENT_SECRET": "env_client_secret",
            # MAGI_プレフィックスの方は設定しない
        }
        
        with patch.dict(os.environ, env_vars):
            self.cli._run_auth_command(["login", "antigravity"])

        # get_auth_provider に渡された AuthContext を検証
        args, _ = mock_get_auth.call_args
        provider_id, context = args
        self.assertEqual(provider_id, "antigravity")
        self.assertEqual(context.client_id, "env_client_id")
        self.assertEqual(context.client_secret, "env_client_secret")

    @patch("magi.cli.main.ProviderConfigLoader")
    @patch("magi.cli.main.get_auth_provider")
    @patch("magi.cli.main.sys.stdin.isatty", return_value=False)
    def test_auth_login_non_interactive_magi_env_vars_priority(
        self, mock_isatty, mock_get_auth, mock_loader
    ):
        """非対話モードで MAGI_ANTIGRAVITY_CLIENT_ID が優先されることを確認"""
        
        mock_loader.return_value.load.return_value.providers = {}
        mock_auth_provider = MagicMock()
        mock_get_auth.return_value = mock_auth_provider

        env_vars = {
            "MAGI_ANTIGRAVITY_CLIENT_ID": "magi_client_id",
            "ANTIGRAVITY_CLIENT_ID": "antigravity_client_id",
            "MAGI_ANTIGRAVITY_CLIENT_SECRET": "magi_client_secret",
        }
        
        with patch.dict(os.environ, env_vars):
            self.cli._run_auth_command(["login", "antigravity"])

        args, _ = mock_get_auth.call_args
        _, context = args
        self.assertEqual(context.client_id, "magi_client_id")
        self.assertEqual(context.client_secret, "magi_client_secret")

    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("magi.cli.main.sys.stdin.isatty", return_value=True)
    @patch("magi.cli.main.ProviderConfigLoader")
    @patch("magi.cli.main.get_auth_provider")
    def test_auth_login_interactive_defaults(
        self, mock_get_auth, mock_loader, mock_isatty, mock_getpass, mock_input
    ):
        """対話モードで環境変数がデフォルト値として使用されることを確認"""
        
        mock_loader.return_value.load.return_value.providers = {}
        # 非同期メソッドのモック
        mock_auth_provider = MagicMock()
        mock_auth_provider.authenticate = AsyncMock(return_value=None)
        mock_get_auth.return_value = mock_auth_provider

        # 入力は空エンターをシミュレート
        mock_input.return_value = ""
        mock_getpass.return_value = ""

        env_vars = {
            "ANTIGRAVITY_CLIENT_ID": "default_client_id",
            "ANTIGRAVITY_CLIENT_SECRET": "default_client_secret",
        }
        
        with patch.dict(os.environ, env_vars):
            # run() でなく内部メソッドを呼ぶが、authenticateはawaitされる
            # しかし _run_auth_command は asyncio.run しているので、そのまま呼ぶ
            self.cli._run_auth_command(["login", "antigravity"])

        args, _ = mock_get_auth.call_args
        _, context = args
        self.assertEqual(context.client_id, "default_client_id")
        self.assertEqual(context.client_secret, "default_client_secret")

    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("magi.cli.main.sys.stdin.isatty", return_value=True)
    @patch("magi.cli.main.yaml.dump")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("magi.cli.main.Path.exists", return_value=False)
    @patch("magi.cli.main.get_auth_provider")
    def test_init_interactive_antigravity_defaults(
        self, mock_get_auth, mock_exists, mock_open, mock_yaml_dump, mock_isatty, mock_getpass, mock_input
    ):
        """initコマンドの対話モードで環境変数がデフォルト値として使用されることを確認"""
        
        # モックの設定
        mock_auth_provider = MagicMock()
        mock_auth_provider.get_token = AsyncMock(return_value="mock_token")
        mock_get_auth.return_value = mock_auth_provider

        # 1. Provider selection (antigravity is index 0 in sorted SUPPORTED_PROVIDERS=["antigravity", ...])
        # SUPPORTED_PROVIDERS is imported in main.py. Let's assume antigravity is there.
        # We need to find the index of 'antigravity' in sorted(SUPPORTED_PROVIDERS).
        from magi.config.provider import SUPPORTED_PROVIDERS
        sorted_providers = sorted(list(SUPPORTED_PROVIDERS))
        antigravity_index = sorted_providers.index("antigravity")
        
        # Inputs:
        # 1. Provider choice (index + 1)
        # 2. Client ID (empty -> use default)
        # 3. Client Secret (empty -> use default) - via getpass
        # 4. Token URL (empty -> use default)
        # 5. Model choice (default=1)
        
        mock_input.side_effect = [
            str(antigravity_index + 1), # Provider choice
            "",                         # Client ID (empty)
            "",                         # Token URL (empty)
            "1",                        # Model choice
        ]
        mock_getpass.side_effect = [""] # Client Secret (empty)

        env_vars = {
            "ANTIGRAVITY_CLIENT_ID": "init_default_id",
            "ANTIGRAVITY_CLIENT_SECRET": "init_default_secret",
        }
        
        with patch.dict(os.environ, env_vars):
            self.cli._run_init_command([""])

        # Check yaml dump content
        # mock_yaml_dump が呼ばれているか確認
        if not mock_yaml_dump.call_args:
            self.fail("yaml.dump was not called. Initialization might have failed.")
            
        args, _ = mock_yaml_dump.call_args
        config_dict = args[0]
        options = config_dict["providers"]["antigravity"]["options"]
        
        self.assertEqual(options["client_id"], "init_default_id")
        self.assertEqual(options["client_secret"], "init_default_secret")

if __name__ == "__main__":
    unittest.main()
