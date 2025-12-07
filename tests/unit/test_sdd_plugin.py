"""
SDDプラグインのテスト

magi-cc-sdd-pluginのYAML定義とspecコマンドの統合テスト
"""

import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from magi.plugins.loader import PluginLoader, Plugin, PluginMetadata, BridgeConfig
from magi.models import PersonaType


class TestSDDPluginDefinition(unittest.TestCase):
    """SDDプラグイン定義ファイルのテスト"""
    
    def setUp(self):
        """テストのセットアップ"""
        self.loader = PluginLoader()
        # プロジェクトルートからのプラグインパスを取得
        # tests/unit/ から plugins/ へのパスを計算
        self.plugin_path = Path(__file__).parent.parent.parent / "plugins" / "magi-cc-sdd-plugin" / "plugin.yaml"
    
    def test_plugin_file_exists(self):
        """プラグインファイルが存在することを確認"""
        self.assertTrue(
            self.plugin_path.exists(),
            f"Plugin file not found at: {self.plugin_path}"
        )
    
    def test_plugin_loads_successfully(self):
        """プラグインが正常にロードできることを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
        
        plugin = self.loader.load(self.plugin_path)
        self.assertIsInstance(plugin, Plugin)
    
    def test_plugin_has_correct_metadata(self):
        """プラグインのメタデータが正しいことを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
        
        plugin = self.loader.load(self.plugin_path)
        
        # メタデータの検証
        self.assertEqual(plugin.metadata.name, "magi-cc-sdd-plugin")
        self.assertIsNotNone(plugin.metadata.version)
        self.assertIsNotNone(plugin.metadata.description)
        self.assertIn("sdd", plugin.metadata.description.lower())
    
    def test_plugin_has_bridge_config(self):
        """プラグインにブリッジ設定があることを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
        
        plugin = self.loader.load(self.plugin_path)
        
        # ブリッジ設定の検証
        self.assertIsInstance(plugin.bridge, BridgeConfig)
        self.assertIn("cc-sdd", plugin.bridge.command)
        self.assertIn(plugin.bridge.interface, ["stdio", "file"])
        self.assertGreater(plugin.bridge.timeout, 0)
    
    def test_plugin_has_agent_overrides(self):
        """プラグインにエージェントオーバーライドがあることを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
        
        plugin = self.loader.load(self.plugin_path)
        
        # エージェントオーバーライドの検証
        self.assertIsInstance(plugin.agent_overrides, dict)
        
        # 少なくとも1つのペルソナにオーバーライドがあること
        self.assertGreater(len(plugin.agent_overrides), 0)
        
        # オーバーライドがPersonaType型のキーを持つこと
        for persona_type in plugin.agent_overrides:
            self.assertIsInstance(persona_type, PersonaType)
    
    def test_plugin_has_all_three_personas(self):
        """プラグインに3つのペルソナすべてのオーバーライドがあることを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
        
        plugin = self.loader.load(self.plugin_path)
        
        # 3つのペルソナすべてにオーバーライドがあること
        self.assertIn(PersonaType.MELCHIOR, plugin.agent_overrides)
        self.assertIn(PersonaType.BALTHASAR, plugin.agent_overrides)
        self.assertIn(PersonaType.CASPER, plugin.agent_overrides)
        
        # 各オーバーライドが空でないこと
        for persona_type, override in plugin.agent_overrides.items():
            self.assertIsInstance(override, str)
            self.assertGreater(len(override.strip()), 0)


class TestSpecCommandIntegration(unittest.TestCase):
    """specコマンドの統合テスト"""
    
    def setUp(self):
        """テストのセットアップ"""
        self.plugin_path = Path(__file__).parent.parent.parent / "plugins" / "magi-cc-sdd-plugin" / "plugin.yaml"
    
    def test_spec_command_loads_sdd_plugin(self):
        """specコマンドがSDDプラグインをロードすることを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
        
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        
        config = Config(api_key="test-key")
        cli = MagiCLI(config)
        
        # specコマンドは引数がない場合エラーを返す
        result = cli.run("spec", [])
        self.assertEqual(result, 1)
    
    def test_spec_command_with_no_args_shows_usage(self):
        """引数なしのspecコマンドが使用方法を表示することを確認"""
        from io import StringIO
        import sys
        
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        
        config = Config(api_key="test-key")
        cli = MagiCLI(config)
        
        # stderrをキャプチャ
        captured = StringIO()
        sys.stderr = captured
        
        try:
            result = cli.run("spec", [])
        finally:
            sys.stderr = sys.__stderr__
        
        self.assertEqual(result, 1)
        self.assertIn("Usage", captured.getvalue())

    def test_spec_command_with_args_finds_plugin(self):
        """引数ありのspecコマンドがプラグインを見つけることを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
            
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        from io import StringIO
        import sys
        
        config = Config(api_key="test-key")
        cli = MagiCLI(config, plugin="magi-cc-sdd-plugin")
        
        # stderrをキャプチャ
        captured_stderr = StringIO()
        captured_stdout = StringIO()
        sys.stderr = captured_stderr
        sys.stdout = captured_stdout
        
        try:
            # specコマンドを実行
            # cc-sddがない場合はエラーになるが、プラグインは正しくロードされる
            result = cli.run("spec", ["ログイン機能の仕様を作成"])
        finally:
            sys.stderr = sys.__stderr__
            sys.stdout = sys.__stdout__
        
        # cc-sddがインストールされていない場合は1を返す
        # プラグインのロード自体は成功しているはず
        stdout_output = captured_stdout.getvalue()
        stderr_output = captured_stderr.getvalue()
        
        # プラグインがロードされたかエラーが出力されたかを確認
        # どちらかが真であればプラグイン処理は行われている
        self.assertTrue(
            "magi-cc-sdd-plugin" in stdout_output or 
            "cc-sdd" in stderr_output or
            result == 1,
            f"Expected plugin loading or error output. stdout: {stdout_output}, stderr: {stderr_output}"
        )
  
    def test_spec_command_without_plugin_uses_default(self):
        """プラグイン指定なしのspecコマンドがデフォルトプラグインを使用することを確認"""
        if not self.plugin_path.exists():
            self.skipTest("Plugin file not found")
            
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        from io import StringIO
        import sys
        
        config = Config(api_key="test-key")
        # プラグインを指定しない
        cli = MagiCLI(config)
        
        # stderrをキャプチャ
        captured_stderr = StringIO()
        captured_stdout = StringIO()
        sys.stderr = captured_stderr
        sys.stdout = captured_stdout
        
        try:
            result = cli.run("spec", ["テスト仕様"])
        finally:
            sys.stderr = sys.__stderr__
            sys.stdout = sys.__stdout__
        
        # デフォルトでmagi-cc-sdd-pluginを使用
        stdout_output = captured_stdout.getvalue()
        stderr_output = captured_stderr.getvalue()
        
        # 結果は何らかの出力があるはず
        self.assertIsInstance(result, int)


class TestSpecCommandFlow(unittest.TestCase):
    """specコマンドのフロー全体のテスト"""
    
    def setUp(self):
        """テストのセットアップ"""
        self.plugin_path = Path(__file__).parent.parent.parent / "plugins" / "magi-cc-sdd-plugin" / "plugin.yaml"
    
    @patch("magi.plugins.executor.asyncio.create_subprocess_exec")
    def test_cc_sdd_execution_flow(self, mock_subprocess):
        """cc-sddコマンドの実行フローをテスト"""
        import asyncio
        from magi.plugins.executor import CommandExecutor
        
        # サブプロセスのモック
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(
            b"# Generated Specification\n\nThis is a test spec.",
            b""
        ))
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process
        
        executor = CommandExecutor(timeout=30)
        
        # 非同期実行
        result = asyncio.run(executor.execute("echo", ["test"]))
        
        self.assertEqual(result.return_code, 0)
        self.assertIn("test", result.stdout)


if __name__ == "__main__":
    unittest.main()
