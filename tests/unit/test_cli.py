"""
CLIレイヤーのユニットテスト

ArgumentParserとMagiCLIのテストを提供
"""

import json
import sys
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch

# テスト対象のモジュールをインポート
from magi.cli.parser import ArgumentParser, ParsedCommand, ValidationResult
from magi.output.formatter import OutputFormat
from magi.plugins.executor import CommandResult
from magi.models import (
    ConsensusResult,
    Decision,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
)


class TestArgumentParser(unittest.TestCase):
    """ArgumentParserのユニットテスト"""

    def setUp(self):
        """テストの準備"""
        self.parser = ArgumentParser()

    def test_parse_help_short(self):
        """短縮形ヘルプオプションのパース"""
        result = self.parser.parse(["-h"])
        self.assertTrue(result.options.get("help"))

    def test_parse_help_long(self):
        """長形式ヘルプオプションのパース"""
        result = self.parser.parse(["--help"])
        self.assertTrue(result.options.get("help"))

    def test_parse_version_short(self):
        """短縮形バージョンオプションのパース"""
        result = self.parser.parse(["-v"])
        self.assertTrue(result.options.get("version"))

    def test_parse_version_long(self):
        """長形式バージョンオプションのパース"""
        result = self.parser.parse(["--version"])
        self.assertTrue(result.options.get("version"))

    def test_parse_empty_args(self):
        """空の引数リストのパース"""
        result = self.parser.parse([])
        self.assertEqual(result.command, "")
        self.assertEqual(result.args, [])

    def test_parse_command_only(self):
        """コマンドのみのパース"""
        result = self.parser.parse(["ask"])
        self.assertEqual(result.command, "ask")
        self.assertEqual(result.args, [])

    def test_parse_command_with_args(self):
        """コマンドと引数のパース"""
        result = self.parser.parse(["ask", "what", "is", "this"])
        self.assertEqual(result.command, "ask")
        self.assertEqual(result.args, ["what", "is", "this"])

    def test_parse_output_format_json(self):
        """JSON形式の出力フォーマットオプション"""
        result = self.parser.parse(["--format", "json", "ask"])
        self.assertEqual(result.output_format, OutputFormat.JSON)

    def test_parse_output_format_markdown(self):
        """Markdown形式の出力フォーマットオプション"""
        result = self.parser.parse(["--format", "markdown", "ask"])
        self.assertEqual(result.output_format, OutputFormat.MARKDOWN)

    def test_parse_default_output_format(self):
        """デフォルト出力フォーマット"""
        result = self.parser.parse(["ask"])
        self.assertEqual(result.output_format, OutputFormat.MARKDOWN)

    def test_parse_plugin_option(self):
        """プラグインオプションのパース"""
        result = self.parser.parse(["--plugin", "magi-cc-sdd-plugin", "spec"])
        self.assertEqual(result.plugin, "magi-cc-sdd-plugin")
        self.assertEqual(result.command, "spec")

    def test_parse_provider_option(self):
        """プロバイダオプションのパース"""
        result = self.parser.parse(["--provider", "openai", "ask"])
        self.assertEqual(result.command, "ask")
        self.assertEqual(result.options.get("provider"), "openai")

    def test_parse_spec_review_flag(self):
        """specコマンドの--reviewオプションのパース"""
        result = self.parser.parse(["spec", "--review", "レビューして"])
        self.assertEqual(result.command, "spec")
        self.assertTrue(result.options.get("review"))
        self.assertEqual(result.args, ["レビューして"])

    def test_parse_plugin_no_value(self):
        """プラグインオプションに値がない場合"""
        result = self.parser.parse(["--plugin"])
        self.assertIsNone(result.plugin)

    def test_validate_valid_command(self):
        """有効なコマンドのバリデーション"""
        parsed = ParsedCommand(
            command="ask",
            args=["question"],
            options={},
            plugin=None,
            output_format=OutputFormat.MARKDOWN
        )
        result = self.parser.validate(parsed)
        self.assertTrue(result.is_valid)

    def test_validate_empty_command(self):
        """空のコマンドのバリデーション"""
        parsed = ParsedCommand(
            command="",
            args=[],
            options={},
            plugin=None,
            output_format=OutputFormat.MARKDOWN
        )
        result = self.parser.validate(parsed)
        self.assertFalse(result.is_valid)
        self.assertIn("command", result.errors[0].lower())

    def test_validate_unknown_command(self):
        """不明なコマンドのバリデーション"""
        parsed = ParsedCommand(
            command="unknown_command",
            args=[],
            options={},
            plugin=None,
            output_format=OutputFormat.MARKDOWN
        )
        result = self.parser.validate(parsed)
        self.assertFalse(result.is_valid)
        self.assertIn("unknown", result.errors[0].lower())

    def test_validate_help_always_valid(self):
        """ヘルプオプションは常に有効"""
        parsed = ParsedCommand(
            command="",
            args=[],
            options={"help": True},
            plugin=None,
            output_format=OutputFormat.MARKDOWN
        )
        result = self.parser.validate(parsed)
        self.assertTrue(result.is_valid)

    def test_validate_version_always_valid(self):
        """バージョンオプションは常に有効"""
        parsed = ParsedCommand(
            command="",
            args=[],
            options={"version": True},
            plugin=None,
            output_format=OutputFormat.MARKDOWN
        )
        result = self.parser.validate(parsed)
        self.assertTrue(result.is_valid)


class TestParsedCommand(unittest.TestCase):
    """ParsedCommandのユニットテスト"""

    def test_creation(self):
        """ParsedCommandの作成"""
        cmd = ParsedCommand(
            command="ask",
            args=["arg1", "arg2"],
            options={"verbose": True},
            plugin="test-plugin",
            output_format=OutputFormat.JSON
        )
        self.assertEqual(cmd.command, "ask")
        self.assertEqual(cmd.args, ["arg1", "arg2"])
        self.assertEqual(cmd.options, {"verbose": True})
        self.assertEqual(cmd.plugin, "test-plugin")
        self.assertEqual(cmd.output_format, OutputFormat.JSON)

    def test_default_plugin_none(self):
        """デフォルトのプラグインはNone"""
        cmd = ParsedCommand(
            command="ask",
            args=[],
            options={},
            plugin=None,
            output_format=OutputFormat.MARKDOWN
        )
        self.assertIsNone(cmd.plugin)


class TestValidationResult(unittest.TestCase):
    """ValidationResultのユニットテスト"""

    def test_valid_result(self):
        """有効な結果"""
        result = ValidationResult(is_valid=True, errors=[])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_invalid_result_with_errors(self):
        """エラーを含む無効な結果"""
        result = ValidationResult(is_valid=False, errors=["Error 1", "Error 2"])
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 2)


class TestMagiCLI(unittest.TestCase):
    """MagiCLIのユニットテスト"""

    def test_run_help(self):
        """ヘルプコマンドの実行"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        config = Config(api_key="test-key")
        cli = MagiCLI(config)

        # ヘルプの実行は成功する
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cli.run("help", [])
            self.assertEqual(result, 0)

    def test_run_version(self):
        """バージョンコマンドの実行"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        config = Config(api_key="test-key")
        cli = MagiCLI(config)

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cli.run("version", [])
            self.assertEqual(result, 0)
            output = mock_stdout.getvalue()
            self.assertIn("magi", output.lower())

    def test_run_invalid_command(self):
        """無効なコマンドの実行"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        config = Config(api_key="test-key")
        cli = MagiCLI(config)

        with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            result = cli.run("invalid_cmd", [])
            self.assertEqual(result, 1)
            output = mock_stderr.getvalue()
            self.assertIn("unknown", output.lower())

    def test_show_help_output(self):
        """ヘルプ出力の確認"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        config = Config(api_key="test-key")
        cli = MagiCLI(config)

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            cli.show_help()
            output = mock_stdout.getvalue()
            self.assertIn("MAGI", output)
            self.assertIn("usage", output.lower())

    def test_show_version_output(self):
        """バージョン出力の確認"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        from magi import __version__

        config = Config(api_key="test-key")
        cli = MagiCLI(config)

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            cli.show_version()
            output = mock_stdout.getvalue()
            self.assertIn(__version__, output)

    def test_run_ask_executes_consensus_and_outputs(self):
        """askコマンドで合議結果を表示する"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        result = ConsensusResult(
            thinking_results={
                PersonaType.MELCHIOR: ThinkingOutput(
                    persona_type=PersonaType.MELCHIOR,
                    content="thinking",
                    timestamp=datetime.utcnow(),
                )
            },
            debate_results=[],
            voting_results={
                PersonaType.MELCHIOR: VoteOutput(
                    persona_type=PersonaType.MELCHIOR,
                    vote=Vote.APPROVE,
                    reason="ok",
                    conditions=[],
                )
            },
            final_decision=Decision.APPROVED,
            exit_code=0,
            all_conditions=[],
        )

        class DummyEngine:
            def __init__(self, *_args, **_kwargs):
                self.events: List[Dict[str, Any]] = []
                self.errors: List[Dict[str, Any]] = []
                self.last_prompt: str | None = None

            async def execute(self, prompt: str, plugin=None):
                self.last_prompt = prompt
                return result

        config = Config(api_key="test-key")
        cli = MagiCLI(config, output_format=OutputFormat.JSON)

        with patch("magi.cli.main.ConsensusEngine", return_value=DummyEngine()) as engine_cls:
            with patch.object(cli, "_has_logging_destination", return_value=True):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    exit_code = cli._run_ask_command(["hello"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"final_decision": "approved"', mock_stdout.getvalue())
        engine_instance = engine_cls.return_value
        self.assertEqual(engine_instance.last_prompt, "hello")

    def test_run_ask_reports_fail_safe_summary(self):
        """フェイルセーフ発生時に理由を表示する"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        result = ConsensusResult(
            thinking_results={},
            debate_results=[],
            voting_results={},
            final_decision=Decision.DENIED,
            exit_code=1,
            all_conditions=[],
        )

        class DummyEngine:
            def __init__(self, *_args, **_kwargs):
                self.events: List[Dict[str, Any]] = [
                    {"type": "quorum.fail_safe", "reason": "quorum 未達", "phase": "voting"}
                ]
                self.errors: List[Dict[str, Any]] = [
                    {"phase": "voting", "reason": "quorum 未達"}
                ]

            async def execute(self, prompt: str, plugin=None):
                return result

        config = Config(api_key="test-key")
        cli = MagiCLI(config, output_format=OutputFormat.JSON)

        with patch("magi.cli.main.ConsensusEngine", return_value=DummyEngine()):
            with patch.object(cli, "_has_logging_destination", return_value=True):
                with patch("sys.stdout", new_callable=StringIO):
                    with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                        exit_code = cli._run_ask_command(["question"])

        self.assertEqual(exit_code, 1)
        self.assertIn("フェイルセーフ", mock_stderr.getvalue())
        self.assertIn("quorum 未達", mock_stderr.getvalue())

    def test_run_ask_warns_when_logger_not_configured(self):
        """ログ出力先未設定時に警告する"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        result = ConsensusResult(
            thinking_results={},
            debate_results=[],
            voting_results={},
            final_decision=Decision.APPROVED,
            exit_code=0,
            all_conditions=[],
        )

        class DummyEngine:
            def __init__(self, *_args, **_kwargs):
                self.events: List[Dict[str, Any]] = []
                self.errors: List[Dict[str, Any]] = []

            async def execute(self, prompt: str, plugin=None):
                return result

        config = Config(api_key="test-key")
        cli = MagiCLI(config, output_format=OutputFormat.JSON)

        with patch("magi.cli.main.ConsensusEngine", return_value=DummyEngine()):
            with patch.object(cli, "_has_logging_destination", return_value=False):
                with patch("sys.stdout", new_callable=StringIO):
                    with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                        cli._run_ask_command(["question"])

        self.assertIn("ログ出力先が設定されていません", mock_stderr.getvalue())

    def test_run_ask_prints_selected_provider(self):
        """選択されたプロバイダを明示的に表示する"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config
        from magi.core.providers import ProviderContext

        result = ConsensusResult(
            thinking_results={},
            debate_results=[],
            voting_results={},
            final_decision=Decision.APPROVED,
            exit_code=0,
            all_conditions=[],
        )

        class DummySelector:
            def __init__(self, context: ProviderContext):
                self.context = context
                self.calls: List[str | None] = []

            def select(self, provider_id: str | None = None) -> ProviderContext:
                self.calls.append(provider_id)
                return self.context

        class DummyFactory:
            def __init__(self):
                self.calls: List[ProviderContext] = []

            def build(self, context: ProviderContext):
                self.calls.append(context)
                return object()

        class DummyEngine:
            def __init__(self, *_args, **_kwargs):
                self.events: List[Dict[str, Any]] = []
                self.errors: List[Dict[str, Any]] = []

            async def execute(self, prompt: str, plugin=None):
                return result

        context = ProviderContext(
            provider_id="openai",
            api_key="k",
            model="gpt-4o",
            used_default=False,
        )
        selector = DummySelector(context)
        factory = DummyFactory()

        config = Config(api_key="test-key")
        cli = MagiCLI(
            config,
            output_format=OutputFormat.JSON,
            provider_selector=selector,
            provider_factory=factory,
        )

        with patch("magi.cli.main.ConsensusEngine", return_value=DummyEngine()):
            with patch.object(cli, "_has_logging_destination", return_value=True):
                with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                    with patch("sys.stdout", new_callable=StringIO):
                        exit_code = cli._run_ask_command(
                            ["hello"],
                            options={"provider": "openai"},
                        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(selector.calls, ["openai"])
        self.assertEqual(factory.calls[0].provider_id, "openai")
        self.assertIn("openai", mock_stderr.getvalue().lower())

    def test_run_spec_review_outputs_status_and_progress(self):
        """spec --reviewがレビュー結果を整形表示し部分失敗を許容する"""
        from magi.cli.main import MagiCLI
        from magi.config.manager import Config

        review_payload = {
            "spec": "# Draft\\ncontent",
            "reviews": [
                {
                    "reviewer_id": "sage-a",
                    "status": "ok",
                    "score": 0.92,
                    "message": "looks good",
                    "timestamp": "2025-12-10T10:00:00Z",
                },
                {
                    "reviewer_id": "sage-b",
                    "status": "failed",
                    "score": 0.0,
                    "message": "timeout",
                    "timestamp": "2025-12-10T10:00:05Z",
                },
                {
                    "reviewer_id": "sage-c",
                    "status": "ok",
                    "score": 0.81,
                    "message": "needs tests",
                    "timestamp": "2025-12-10T10:00:07Z",
                },
            ],
        }

        config = Config(api_key="test-key")
        cli = MagiCLI(config, output_format=OutputFormat.MARKDOWN)
        plugin_path = Path(__file__).parent.parent.parent / "plugins" / "magi-cc-sdd-plugin" / "plugin.yaml"

        if not plugin_path.exists():
            self.skipTest("magi-cc-sdd-plugin not found")

        with patch.object(
            cli,
            "_execute_cc_sdd",
            return_value=CommandResult(
                stdout=json.dumps(review_payload),
                stderr="",
                return_code=0,
                execution_time=0.4,
            ),
        ):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                exit_code = cli._run_spec_command(["--review", "ログイン仕様をレビュー"])

        output = mock_stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("overall 2/3 complete", output)
        self.assertIn("sage-a", output)
        self.assertIn("0.92", output)
        self.assertIn("sage-b", output)
        self.assertIn("timeout", output)
        self.assertIn("max_attempts=3", output)


class TestMainEntry(unittest.TestCase):
    """メインエントリーポイントのテスト"""

    def test_main_with_help(self):
        """--helpオプションでの起動"""
        from magi.__main__ import main

        result = main(["--help"])
        self.assertEqual(result, 0)

    def test_main_with_version(self):
        """--versionオプションでの起動"""
        from magi.__main__ import main

        result = main(["--version"])
        self.assertEqual(result, 0)

    def test_main_empty_args(self):
        """引数なしでの起動"""
        from magi.__main__ import main

        result = main([])
        self.assertEqual(result, 0)  # ヘルプを表示

    def test_main_invalid_command(self):
        """無効なコマンドでの起動"""
        from magi.__main__ import main

        with patch('sys.stderr', new_callable=StringIO):
            result = main(["invalid_command"])
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
