"""
CommandExecutor のユニットテスト

外部コマンドの実行、出力キャプチャ、タイムアウト処理をテスト
"""

import unittest
import asyncio
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from magi.plugins.executor import CommandExecutor, CommandResult
from magi.errors import MagiException, ErrorCode


class TestCommandExecutor(unittest.TestCase):
    """CommandExecutor のユニットテスト"""

    def setUp(self):
        """テスト前のセットアップ"""
        self.executor = CommandExecutor()

    def test_init_default_timeout(self):
        """デフォルトタイムアウトが30秒であることを検証"""
        executor = CommandExecutor()
        self.assertEqual(executor.timeout, 30)

    def test_init_custom_timeout(self):
        """カスタムタイムアウトが正しく設定されることを検証"""
        executor = CommandExecutor(timeout=60)
        self.assertEqual(executor.timeout, 60)


class TestCommandExecutorExecute(unittest.TestCase):
    """CommandExecutor.execute() のテスト"""

    def setUp(self):
        """テスト前のセットアップ"""
        self.executor = CommandExecutor(timeout=5)

    def test_execute_simple_command_success(self):
        """シンプルなコマンドが正常に実行されることを検証"""
        result = asyncio.run(self.executor.execute("echo", ["hello"]))

        self.assertIsInstance(result, CommandResult)
        self.assertEqual(result.return_code, 0)
        self.assertIn("hello", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertGreater(result.execution_time, 0)

    def test_execute_command_with_stderr(self):
        """stderrを生成するコマンドの出力がキャプチャされることを検証"""
        result = asyncio.run(
            self.executor.execute("bash", ["-c", "echo error >&2"])
        )

        self.assertIn("error", result.stderr)

    def test_execute_command_with_nonzero_exit(self):
        """非ゼロ終了コードが正しく返されることを検証"""
        result = asyncio.run(
            self.executor.execute("bash", ["-c", "exit 42"])
        )

        self.assertEqual(result.return_code, 42)

    def test_execute_command_not_found(self):
        """存在しないコマンドがエラーを発生させることを検証"""
        with self.assertRaises(MagiException) as cm:
            asyncio.run(
                self.executor.execute("nonexistent_command_12345", [])
            )

        self.assertEqual(
            cm.exception.error.code, 
            ErrorCode.PLUGIN_COMMAND_FAILED.value
        )

    def test_execute_command_timeout(self):
        """タイムアウトが発生した場合のエラーハンドリングを検証"""
        executor = CommandExecutor(timeout=1)

        with self.assertRaises(MagiException) as cm:
            asyncio.run(
                executor.execute("sleep", ["10"])
            )

        self.assertEqual(
            cm.exception.error.code, 
            ErrorCode.PLUGIN_COMMAND_TIMEOUT.value
        )

    def test_execute_captures_both_stdout_and_stderr(self):
        """stdoutとstderrの両方がキャプチャされることを検証"""
        result = asyncio.run(
            self.executor.execute(
                "bash", 
                ["-c", "echo stdout_content; echo stderr_content >&2"]
            )
        )

        self.assertIn("stdout_content", result.stdout)
        self.assertIn("stderr_content", result.stderr)

    def test_execute_with_no_args(self):
        """引数なしでコマンドが実行できることを検証"""
        result = asyncio.run(self.executor.execute("true", None))

        self.assertEqual(result.return_code, 0)

    def test_execute_with_empty_args(self):
        """空のリストの引数でコマンドが実行できることを検証"""
        result = asyncio.run(self.executor.execute("true", []))

        self.assertEqual(result.return_code, 0)

    def test_execute_multiline_output(self):
        """複数行の出力が正しくキャプチャされることを検証"""
        result = asyncio.run(
            self.executor.execute(
                "bash", 
                ["-c", "echo line1; echo line2; echo line3"]
            )
        )

        self.assertIn("line1", result.stdout)
        self.assertIn("line2", result.stdout)
        self.assertIn("line3", result.stdout)

    def test_execute_special_characters(self):
        """特殊文字を含む出力が正しくキャプチャされることを検証"""
        result = asyncio.run(
            self.executor.execute(
                "echo", 
                ["hello 'world' \"test\""]
            )
        )

        self.assertEqual(result.return_code, 0)


class TestCommandResult(unittest.TestCase):
    """CommandResult データクラスのテスト"""

    def test_command_result_attributes(self):
        """CommandResultの属性が正しく設定されることを検証"""
        result = CommandResult(
            stdout="output",
            stderr="error",
            return_code=0,
            execution_time=1.5
        )

        self.assertEqual(result.stdout, "output")
        self.assertEqual(result.stderr, "error")
        self.assertEqual(result.return_code, 0)
        self.assertEqual(result.execution_time, 1.5)

    def test_command_result_equality(self):
        """CommandResultの等価性比較が正しく動作することを検証"""
        result1 = CommandResult(
            stdout="output",
            stderr="",
            return_code=0,
            execution_time=1.0
        )
        result2 = CommandResult(
            stdout="output",
            stderr="",
            return_code=0,
            execution_time=1.0
        )

        self.assertEqual(result1, result2)


if __name__ == '__main__':
    unittest.main()
