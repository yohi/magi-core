"""
BridgeAdapter のユニットテスト
"""

import asyncio
import unittest
from unittest.mock import AsyncMock

from magi.core.providers import ProviderContext
from magi.errors import ErrorCode, MagiException
from magi.plugins.bridge import BridgeAdapter
from magi.plugins.executor import CommandResult


class DummyGuard:
    """PluginGuard互換のモック"""

    def __init__(self):
        self.calls = []

    def validate(self, command, args):
        self.calls.append((command, list(args)))
        return list(args)


class DummyExecutor:
    """CommandExecutor互換のモック"""

    def __init__(self, result: CommandResult):
        self.result = result
        self.calls = []

    async def execute(self, command, args=None, env=None):
        self.calls.append({"command": command, "args": args, "env": env})
        return self.result


class TestBridgeAdapter(unittest.TestCase):
    """BridgeAdapter の挙動を検証"""

    def setUp(self):
        self.context = ProviderContext(
            provider_id="openai",
            api_key="secret-key",
            model="gpt-4o",
            endpoint="https://api.openai.com",
        )

    def test_rejects_unsupported_provider(self):
        """未対応プロバイダをfail-fastで拒否する"""
        adapter = BridgeAdapter(
            supported_providers={"anthropic"},
            guard=DummyGuard(),
            executor=DummyExecutor(
                CommandResult(stdout="", stderr="", return_code=0, execution_time=0.1)
            ),
        )

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.invoke("echo", ["ok"], self.context))

        self.assertEqual(exc.exception.error.code, ErrorCode.CONFIG_INVALID_VALUE.value)

    def test_passes_provider_env_and_validates_args(self):
        """鍵を環境変数で子プロセスに渡し、Guard検証を通す"""
        guard = DummyGuard()
        executor = DummyExecutor(
            CommandResult(stdout="ok", stderr="", return_code=0, execution_time=0.1)
        )
        adapter = BridgeAdapter(
            guard=guard,
            executor=executor,
        )

        result = asyncio.run(
            adapter.invoke("echo", ["hello"], self.context)
        )

        self.assertEqual(result.stdout, "ok")
        self.assertEqual(guard.calls[0][0], "echo")
        self.assertEqual(guard.calls[0][1], ["hello"])
        call_env = executor.calls[0]["env"]
        self.assertEqual(call_env.get("MAGI_PROVIDER"), "openai")
        self.assertEqual(call_env.get("MAGI_PROVIDER_MODEL"), "gpt-4o")
        self.assertEqual(call_env.get("MAGI_PROVIDER_API_KEY"), "secret-key")

    def test_auth_error_is_wrapped_with_provider_context(self):
        """認証エラーをprovider文脈付きで返す"""
        guard = DummyGuard()
        executor = DummyExecutor(
            CommandResult(
                stdout="",
                stderr="authentication failed",
                return_code=1,
                execution_time=0.1,
            )
        )
        adapter = BridgeAdapter(
            guard=guard,
            executor=executor,
        )

        with self.assertRaises(MagiException) as exc:
            asyncio.run(adapter.invoke("echo", ["x"], self.context))

        self.assertEqual(exc.exception.error.code, ErrorCode.PLUGIN_COMMAND_FAILED.value)
        self.assertIn("authentication", exc.exception.error.message.lower())
        # providerは安全な辞書形式で返される
        provider_dict = exc.exception.error.details.get("provider")
        self.assertIsInstance(provider_dict, dict)
        self.assertEqual(provider_dict.get("provider_id"), "openai")
        self.assertEqual(provider_dict.get("model"), "gpt-4o")
        self.assertEqual(provider_dict.get("endpoint"), "https://api.openai.com")
        # APIキーはマスクされている
        self.assertNotEqual(provider_dict.get("api_key"), "secret-key")
        self.assertIn("***", provider_dict.get("api_key", ""))
        # stderrはサニタイズされている
        stderr = exc.exception.error.details.get("stderr")
        self.assertIsNotNone(stderr)
        self.assertEqual(stderr, "authentication failed")  # このケースではマスク不要


if __name__ == "__main__":
    unittest.main()
