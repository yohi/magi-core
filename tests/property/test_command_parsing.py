"""
コマンド解析のプロパティテスト

**Feature: magi-core, Property 1: コマンド解析の正確性**
**Validates: Requirements 1.1, 1.2**
"""

import unittest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from magi.cli.parser import (
    ArgumentParser,
    ParsedCommand,
    ValidationResult,
    VALID_COMMANDS,
)
from magi.output.formatter import OutputFormat


class TestCommandParsingProperty(unittest.TestCase):
    """
    **Feature: magi-core, Property 1: コマンド解析の正確性**
    **Validates: Requirements 1.1, 1.2**

    For any コマンド文字列に対して、有効なコマンドであれば適切なハンドラーに
    処理が委譲され、無効なコマンドであればエラーメッセージが生成される
    """

    def setUp(self):
        """テストの準備"""
        self.parser = ArgumentParser()

    @given(command=st.sampled_from(list(VALID_COMMANDS)))
    @settings(max_examples=100)
    def test_valid_commands_always_valid(self, command: str):
        """有効なコマンドは常にバリデーションを通過する"""
        result = self.parser.parse([command])
        validation = self.parser.validate(result)
        self.assertTrue(validation.is_valid)
        self.assertEqual(result.command, command)

    @given(command=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_unknown_commands_are_rejected(self, command: str):
        """不明なコマンドはバリデーションで拒否される"""
        # 有効なコマンドでなく、オプションでもないことを仮定
        assume(command not in VALID_COMMANDS)
        assume(not command.startswith("-"))
        assume(command.strip() == command)  # 前後に空白がない

        result = self.parser.parse([command])
        validation = self.parser.validate(result)

        self.assertFalse(validation.is_valid)
        self.assertTrue(len(validation.errors) > 0)
        self.assertIn("unknown", validation.errors[0].lower())

    @given(args=st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=10))
    @settings(max_examples=100)
    def test_args_are_preserved(self, args: list):
        """コマンド引数は保存される"""
        # 引数がオプションやコマンドでないことを仮定
        clean_args = [arg for arg in args if not arg.startswith("-") and arg.strip()]
        assume(len(clean_args) > 0)

        all_argv = ["ask"] + clean_args
        result = self.parser.parse(all_argv)

        self.assertEqual(result.command, "ask")
        self.assertEqual(result.args, clean_args)

    @given(st.booleans())
    @settings(max_examples=100)
    def test_help_option_always_works(self, use_short: bool):
        """--helpまたは-hオプションは常に機能する"""
        option = "-h" if use_short else "--help"
        result = self.parser.parse([option])

        self.assertTrue(result.options.get("help"))
        validation = self.parser.validate(result)
        self.assertTrue(validation.is_valid)

    @given(st.booleans())
    @settings(max_examples=100)
    def test_version_option_always_works(self, use_short: bool):
        """--versionまたは-vオプションは常に機能する"""
        option = "-v" if use_short else "--version"
        result = self.parser.parse([option])

        self.assertTrue(result.options.get("version"))
        validation = self.parser.validate(result)
        self.assertTrue(validation.is_valid)

    @given(
        format_value=st.sampled_from(["json", "markdown", "JSON", "MARKDOWN", "Json", "Markdown"]),
        command=st.sampled_from(list(VALID_COMMANDS))
    )
    @settings(max_examples=100)
    def test_format_option_case_insensitive(self, format_value: str, command: str):
        """--formatオプションは大文字小文字を区別しない"""
        result = self.parser.parse(["--format", format_value, command])

        if format_value.lower() == "json":
            self.assertEqual(result.output_format, OutputFormat.JSON)
        else:
            self.assertEqual(result.output_format, OutputFormat.MARKDOWN)

    @given(plugin_name=st.text(min_size=1, max_size=50).filter(lambda x: not x.startswith("-")))
    @settings(max_examples=100)
    def test_plugin_option_preserved(self, plugin_name: str):
        """--pluginオプションの値は正しく保存される"""
        assume(plugin_name.strip())

        result = self.parser.parse(["--plugin", plugin_name, "ask"])

        self.assertEqual(result.plugin, plugin_name)
        self.assertEqual(result.command, "ask")

    @given(command=st.sampled_from(list(VALID_COMMANDS)))
    @settings(max_examples=100)
    def test_default_output_format_is_markdown(self, command: str):
        """デフォルトの出力形式はMarkdown"""
        result = self.parser.parse([command])

        self.assertEqual(result.output_format, OutputFormat.MARKDOWN)


class TestValidationResultProperty(unittest.TestCase):
    """ValidationResultのプロパティテスト"""

    @given(
        is_valid=st.booleans(),
        errors=st.lists(st.text(min_size=1, max_size=100), min_size=0, max_size=5)
    )
    @settings(max_examples=100)
    def test_validation_result_consistency(self, is_valid: bool, errors: list):
        """ValidationResultは有効/無効とエラーリストを正しく保持する"""
        result = ValidationResult(is_valid=is_valid, errors=errors)

        self.assertEqual(result.is_valid, is_valid)
        self.assertEqual(result.errors, errors)


class TestParsedCommandProperty(unittest.TestCase):
    """ParsedCommandのプロパティテスト"""

    @given(
        command=st.text(max_size=20),
        args=st.lists(st.text(max_size=20), max_size=10),
        plugin=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        format_type=st.sampled_from([OutputFormat.JSON, OutputFormat.MARKDOWN])
    )
    @settings(max_examples=100)
    def test_parsed_command_preserves_data(
        self, command: str, args: list, plugin: str | None, format_type: OutputFormat
    ):
        """ParsedCommandは全データを正しく保持する"""
        options = {"test": True}

        parsed = ParsedCommand(
            command=command,
            args=args,
            options=options,
            plugin=plugin,
            output_format=format_type
        )

        self.assertEqual(parsed.command, command)
        self.assertEqual(parsed.args, args)
        self.assertEqual(parsed.options, options)
        self.assertEqual(parsed.plugin, plugin)
        self.assertEqual(parsed.output_format, format_type)


if __name__ == "__main__":
    unittest.main()
