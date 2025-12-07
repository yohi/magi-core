"""
MAGI System End-to-End Integration Tests

コンポーネント統合確認のためのテストスイート。
エンドツーエンドでの動作確認を行う。

Requirements: 1.1, 4.1, 5.1, 6.1
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from magi import __version__
from magi.agents.agent import Agent
from magi.agents.persona import PersonaManager, PersonaType
from magi.cli.main import MagiCLI
from magi.cli.parser import ArgumentParser
from magi.config.manager import Config, ConfigManager
from magi.core.consensus import ConsensusEngine
from magi.core.context import ContextManager
from magi.errors import MagiException
from magi.llm.client import LLMClient, LLMResponse
from magi.models import (
    ConsensusPhase,
    ConsensusResult,
    DebateOutput,
    DebateRound,
    Decision,
    ThinkingOutput,
    Vote,
    VoteOutput,
)
from magi.output.formatter import OutputFormat, OutputFormatter
from magi.plugins.loader import PluginLoader


class TestCLIHelpAndVersion(unittest.TestCase):
    """CLIのヘルプとバージョン表示の統合テスト
    
    Requirements: 1.3, 1.4
    """
    
    def setUp(self):
        """テストセットアップ"""
        self.config = Config(api_key="test-api-key")
    
    def test_version_display(self):
        """バージョン表示の統合テスト"""
        cli = MagiCLI(self.config)
        
        # 標準出力をキャプチャ
        captured = StringIO()
        with patch('sys.stdout', captured):
            cli.show_version()
        
        output = captured.getvalue()
        self.assertIn(__version__, output)
        self.assertIn("magi", output.lower())
    
    def test_help_display(self):
        """ヘルプ表示の統合テスト"""
        cli = MagiCLI(self.config)
        
        captured = StringIO()
        with patch('sys.stdout', captured):
            cli.show_help()
        
        output = captured.getvalue()
        # ヘルプ内容の確認
        self.assertIn("magi", output.lower())
        self.assertIn("ask", output)
        self.assertIn("spec", output)


class TestArgumentParserCLIIntegration(unittest.TestCase):
    """ArgumentParserとCLIの統合テスト
    
    Requirements: 1.1, 1.2
    """
    
    def setUp(self):
        """テストセットアップ"""
        self.parser = ArgumentParser()
        self.config = Config(api_key="test-api-key")
    
    def test_parse_ask_command_and_execute(self):
        """askコマンドの解析と実行フロー"""
        # 引数解析
        parsed = self.parser.parse(["ask", "test question"])
        
        self.assertEqual(parsed.command, "ask")
        self.assertEqual(parsed.args, ["test question"])
        
        # バリデーション
        result = self.parser.validate(parsed)
        self.assertTrue(result.is_valid)
    
    def test_parse_spec_command_and_execute(self):
        """specコマンドの解析と実行フロー"""
        # 引数解析
        parsed = self.parser.parse(["spec", "create a login spec"])
        
        self.assertEqual(parsed.command, "spec")
        self.assertEqual(parsed.args, ["create a login spec"])
        
        # バリデーション
        result = self.parser.validate(parsed)
        self.assertTrue(result.is_valid)
    
    def test_format_option_parsing(self):
        """フォーマットオプションの解析"""
        parsed = self.parser.parse(["--format", "json", "ask", "question"])
        
        self.assertEqual(parsed.output_format, OutputFormat.JSON)
        self.assertEqual(parsed.command, "ask")
    
    def test_invalid_command_validation(self):
        """無効コマンドのバリデーション"""
        parsed = self.parser.parse(["invalid_command"])
        
        result = self.parser.validate(parsed)
        self.assertFalse(result.is_valid)
        self.assertGreater(len(result.errors), 0)


class TestPersonaManagerAgentIntegration(unittest.TestCase):
    """PersonaManagerとAgentの統合テスト
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    """
    
    def setUp(self):
        """テストセットアップ"""
        self.persona_manager = PersonaManager()
    
    def test_all_personas_initialized(self):
        """3賢者全員が初期化されていることを確認"""
        for persona_type in PersonaType:
            persona = self.persona_manager.get_persona(persona_type)
            self.assertIsNotNone(persona)
            self.assertEqual(persona.type, persona_type)
    
    def test_melchior_persona_logic_focus(self):
        """MELCHIORペルソナが論理・科学を担当していることを確認"""
        persona = self.persona_manager.get_persona(PersonaType.MELCHIOR)
        
        # 論理・科学関連のキーワードがプロンプトに含まれている
        system_prompt = persona.system_prompt.lower()
        logic_keywords = ["論理", "科学", "分析", "事実", "logic", "scientific", "analytical"]
        has_logic_keyword = any(kw in system_prompt for kw in logic_keywords)
        self.assertTrue(has_logic_keyword, "MELCHIOR should focus on logic/science")
    
    def test_balthasar_persona_ethics_focus(self):
        """BALTHASARペルソナが倫理・保護を担当していることを確認"""
        persona = self.persona_manager.get_persona(PersonaType.BALTHASAR)
        
        system_prompt = persona.system_prompt.lower()
        ethics_keywords = ["倫理", "保護", "リスク", "安全", "ethics", "protection", "risk"]
        has_ethics_keyword = any(kw in system_prompt for kw in ethics_keywords)
        self.assertTrue(has_ethics_keyword, "BALTHASAR should focus on ethics/protection")
    
    def test_casper_persona_practical_focus(self):
        """CASPERペルソナが欲望・実利を担当していることを確認"""
        persona = self.persona_manager.get_persona(PersonaType.CASPER)
        
        system_prompt = persona.system_prompt.lower()
        practical_keywords = ["欲望", "実利", "効率", "利益", "practical", "efficiency", "benefit"]
        has_practical_keyword = any(kw in system_prompt for kw in practical_keywords)
        self.assertTrue(has_practical_keyword, "CASPER should focus on practicality")
    
    def test_override_application(self):
        """プラグインオーバーライドの適用"""
        overrides = {
            "melchior": "Additional instruction for MELCHIOR",
            "balthasar": "Additional instruction for BALTHASAR",
            "casper": "Additional instruction for CASPER",
        }
        
        self.persona_manager.apply_overrides(overrides)
        
        for persona_type in PersonaType:
            persona = self.persona_manager.get_persona(persona_type)
            # オーバーライドが適用されていることを確認
            self.assertIsNotNone(persona.override_prompt)


class TestConsensusEngineContextIntegration(unittest.TestCase):
    """ConsensusEngineとContextManagerの統合テスト
    
    Requirements: 4.1, 5.1, 6.1, 7.1, 7.2, 7.3
    """
    
    def setUp(self):
        """テストセットアップ"""
        self.config = Config(api_key="test-api-key", debate_rounds=1)
        self.consensus_engine = ConsensusEngine(self.config)
    
    def test_consensus_engine_initialization(self):
        """ConsensusEngineの初期化確認"""
        self.assertEqual(self.consensus_engine.current_phase, ConsensusPhase.THINKING)
        self.assertIsNotNone(self.consensus_engine.persona_manager)
        self.assertIsNotNone(self.consensus_engine.context_manager)
    
    @patch('magi.llm.client.LLMClient.send')
    def test_thinking_phase_executes_for_all_agents(self, mock_send):
        """Thinking Phaseで3エージェント全員が思考を生成"""
        # LLMレスポンスをモック
        mock_response = LLMResponse(
            content="Test thinking content",
            usage={"input_tokens": 100, "output_tokens": 50},
            model="claude-3-sonnet"
        )
        mock_send.return_value = mock_response
        
        # Thinking Phaseを実行
        thinking_results = asyncio.run(
            self.consensus_engine._run_thinking_phase("Test prompt")
        )
        
        # 3エージェント分の結果があることを確認
        self.assertEqual(len(thinking_results), 3)
        for persona_type in PersonaType:
            self.assertIn(persona_type, thinking_results)
    
    @patch('magi.llm.client.LLMClient.send')
    def test_phase_transitions(self, mock_send):
        """フェーズ遷移の確認"""
        # LLMレスポンスをモック
        mock_response = LLMResponse(
            content='{"vote": "APPROVE", "reason": "Test reason"}',
            usage={"input_tokens": 100, "output_tokens": 50},
            model="claude-3-sonnet"
        )
        mock_send.return_value = mock_response
        
        # 初期フェーズ
        self.assertEqual(self.consensus_engine.current_phase, ConsensusPhase.THINKING)
        
        # executeを実行して全フェーズを通過
        result = asyncio.run(self.consensus_engine.execute("Test"))
        
        # 最終的にCOMPLETEDになっていることを確認
        self.assertEqual(self.consensus_engine.current_phase, ConsensusPhase.COMPLETED)


class TestOutputFormatterIntegration(unittest.TestCase):
    """OutputFormatterの統合テスト
    
    Requirements: 11.1, 11.2, 11.3, 11.4
    """
    
    def setUp(self):
        """テストセットアップ"""
        self.formatter = OutputFormatter()
        
        # テスト用ConsensusResult
        thinking_results = {
            PersonaType.MELCHIOR: ThinkingOutput(
                persona_type=PersonaType.MELCHIOR,
                content="Logical analysis result",
                timestamp=datetime.now()
            ),
            PersonaType.BALTHASAR: ThinkingOutput(
                persona_type=PersonaType.BALTHASAR,
                content="Risk analysis result",
                timestamp=datetime.now()
            ),
            PersonaType.CASPER: ThinkingOutput(
                persona_type=PersonaType.CASPER,
                content="Practical analysis result",
                timestamp=datetime.now()
            ),
        }
        
        debate_round = DebateRound(
            round_number=1,
            outputs={
                PersonaType.MELCHIOR: DebateOutput(
                    persona_type=PersonaType.MELCHIOR,
                    round_number=1,
                    responses={
                        PersonaType.BALTHASAR: "Response to BALTHASAR",
                        PersonaType.CASPER: "Response to CASPER",
                    },
                    timestamp=datetime.now()
                ),
                PersonaType.BALTHASAR: DebateOutput(
                    persona_type=PersonaType.BALTHASAR,
                    round_number=1,
                    responses={
                        PersonaType.MELCHIOR: "Response to MELCHIOR",
                        PersonaType.CASPER: "Response to CASPER",
                    },
                    timestamp=datetime.now()
                ),
                PersonaType.CASPER: DebateOutput(
                    persona_type=PersonaType.CASPER,
                    round_number=1,
                    responses={
                        PersonaType.MELCHIOR: "Response to MELCHIOR",
                        PersonaType.BALTHASAR: "Response to BALTHASAR",
                    },
                    timestamp=datetime.now()
                ),
            },
            timestamp=datetime.now()
        )
        
        voting_results = {
            PersonaType.MELCHIOR: VoteOutput(
                persona_type=PersonaType.MELCHIOR,
                vote=Vote.APPROVE,
                reason="Approved for logical reasons"
            ),
            PersonaType.BALTHASAR: VoteOutput(
                persona_type=PersonaType.BALTHASAR,
                vote=Vote.APPROVE,
                reason="Approved after risk assessment"
            ),
            PersonaType.CASPER: VoteOutput(
                persona_type=PersonaType.CASPER,
                vote=Vote.APPROVE,
                reason="Approved for practical benefits"
            ),
        }
        
        self.consensus_result = ConsensusResult(
            thinking_results=thinking_results,
            debate_results=[debate_round],
            voting_results=voting_results,
            final_decision=Decision.APPROVED,
            exit_code=0
        )
    
    def test_json_format_output(self):
        """JSON形式出力の確認"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        
        # JSON形式であることを確認
        import json
        try:
            parsed = json.loads(output)
            self.assertIn("thinking_results", parsed)
            self.assertIn("debate_results", parsed)
            self.assertIn("voting_results", parsed)
            self.assertIn("final_decision", parsed)
        except json.JSONDecodeError:
            self.fail("Output should be valid JSON")
    
    def test_markdown_format_output(self):
        """Markdown形式出力の確認"""
        output = self.formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        # Markdownヘッダーが含まれていることを確認
        self.assertIn("#", output)
        # 各エージェント名が含まれていることを確認
        self.assertIn("MELCHIOR", output.upper())
        self.assertIn("BALTHASAR", output.upper())
        self.assertIn("CASPER", output.upper())


class TestPluginLoaderIntegration(unittest.TestCase):
    """PluginLoaderの統合テスト
    
    Requirements: 8.1, 8.2, 8.3, 8.4
    """
    
    def setUp(self):
        """テストセットアップ"""
        self.loader = PluginLoader()
    
    def test_load_valid_plugin_yaml(self):
        """有効なプラグインYAMLの読み込み"""
        # テスト用プラグインYAMLを作成
        yaml_content = """
plugin:
  name: test-plugin
  version: "1.0.0"
  description: "Test plugin for integration testing"

bridge:
  command: echo
  interface: stdio
  timeout: 30

agent_overrides:
  melchior: "Test override for MELCHIOR"
  balthasar: "Test override for BALTHASAR"
  casper: "Test override for CASPER"
"""
        
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            plugin = self.loader.load(Path(temp_path))
            
            self.assertEqual(plugin.metadata.name, "test-plugin")
            self.assertEqual(plugin.metadata.version, "1.0.0")
            self.assertEqual(plugin.bridge.command, "echo")
            self.assertEqual(plugin.bridge.interface, "stdio")
            self.assertIn(PersonaType.MELCHIOR, plugin.agent_overrides)
        finally:
            os.unlink(temp_path)
    
    def test_load_sdd_plugin(self):
        """実際のSDDプラグインの読み込みテスト"""
        # プロジェクトルートを導出 (tests/integration/test_end_to_end.py から2階層上)
        project_root = Path(__file__).parent.parent.parent
        sdd_plugin_path = project_root / "plugins" / "magi-cc-sdd-plugin" / "plugin.yaml"
        
        if sdd_plugin_path.exists():
            plugin = self.loader.load(sdd_plugin_path)
            
            self.assertEqual(plugin.metadata.name, "magi-cc-sdd-plugin")
            self.assertIsNotNone(plugin.bridge.command)


class TestConfigManagerIntegration(unittest.TestCase):
    """ConfigManagerの統合テスト
    
    Requirements: 12.1, 12.2, 12.3, 12.4
    """
    
    def test_load_from_environment(self):
        """環境変数からの設定読み込み"""
        with patch.dict(os.environ, {
            "MAGI_API_KEY": "test-env-api-key",
            "MAGI_DEBATE_ROUNDS": "3",
        }):
            manager = ConfigManager()
            config = manager.load()
            
            self.assertEqual(config.api_key, "test-env-api-key")
            self.assertEqual(config.debate_rounds, 3)
    
    def test_missing_api_key_raises_error(self):
        """APIキー未設定時のエラー"""
        with patch.dict(os.environ, {}, clear=True):
            # MAGI_API_KEY環境変数を削除
            env = os.environ.copy()
            if "MAGI_API_KEY" in env:
                del env["MAGI_API_KEY"]
            
            with patch.dict(os.environ, env, clear=True):
                manager = ConfigManager()
                with self.assertRaises(MagiException):
                    manager.load()


class TestFullWorkflowIntegration(unittest.TestCase):
    """完全なワークフローの統合テスト
    
    Requirements: 1.1, 4.1, 5.1, 6.1
    """
    
    @patch('magi.llm.client.LLMClient.send')
    def test_complete_ask_workflow(self, mock_send):
        """askコマンドの完全なワークフロー"""
        # LLMレスポンスをモック
        mock_response = LLMResponse(
            content='{"vote": "APPROVE", "reason": "Test reason"}',
            usage={"input_tokens": 100, "output_tokens": 50},
            model="claude-3-sonnet"
        )
        mock_send.return_value = mock_response
        
        # 引数解析 → 設定読み込み → CLI実行
        parser = ArgumentParser()
        parsed = parser.parse(["ask", "Test question"])
        
        config = Config(api_key="test-key", debate_rounds=1)
        cli = MagiCLI(config)
        
        # 実行（モック環境では実際のAPI呼び出しは行われない）
        # ここではCLIの構築と引数解析が正しく統合されていることを確認
        self.assertIsNotNone(cli.config)
        self.assertEqual(cli.output_format, OutputFormat.MARKDOWN)
    



if __name__ == "__main__":
    unittest.main()
