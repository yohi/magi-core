"""Agentクラスのユニットテスト

個別エージェントの実装をテストする。

Requirements: 3.2, 3.3, 3.4, 4.1
"""
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from magi.models import PersonaType, Vote


class TestAgent(unittest.TestCase):
    """Agentクラスのテスト"""

    def test_agent_creation(self):
        """Agentを正しく作成できる"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="論理と科学の視点から分析します。"
        )
        mock_client = MagicMock(spec=LLMClient)

        agent = Agent(persona=persona, llm_client=mock_client)

        self.assertEqual(agent.persona, persona)
        self.assertEqual(agent.llm_client, mock_client)


class TestAgentThink(unittest.IsolatedAsyncioTestCase):
    """Agent.thinkメソッドのテスト"""

    async def test_think_generates_output(self):
        """thinkメソッドはThinkingOutputを生成する"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="論理と科学の視点から分析します。"
        )

        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content="これは論理的な分析です。",
            usage={"input_tokens": 100, "output_tokens": 50},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)
        result = await agent.think("この提案について分析してください。")

        self.assertEqual(result.persona_type, PersonaType.MELCHIOR)
        self.assertEqual(result.content, "これは論理的な分析です。")
        self.assertIsInstance(result.timestamp, datetime)

    async def test_think_uses_system_prompt(self):
        """thinkはペルソナのsystem_promptを使用する"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse, LLMRequest

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="基本プロンプト",
            override_prompt="追加指示"
        )

        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content="分析結果",
            usage={"input_tokens": 100, "output_tokens": 50},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)
        await agent.think("プロンプト")

        # sendが呼ばれたことを確認
        mock_client.send.assert_called_once()

        # LLMRequestの内容を確認
        call_args = mock_client.send.call_args
        request = call_args[0][0]
        self.assertIsInstance(request, LLMRequest)
        self.assertEqual(request.system_prompt, "基本プロンプト\n\n追加指示")


class TestAgentDebate(unittest.IsolatedAsyncioTestCase):
    """Agent.debateメソッドのテスト"""

    async def test_debate_generates_output(self):
        """debateメソッドはDebateOutputを生成する"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse

        persona = Persona(
            type=PersonaType.BALTHASAR,
            name="BALTHASAR-2",
            base_prompt="リスク回避の視点から分析します。"
        )

        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content="MELCHIORの意見に対して：リスクがあります。",
            usage={"input_tokens": 150, "output_tokens": 75},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)

        others_thoughts = {
            PersonaType.MELCHIOR: "論理的に正しいです。",
            PersonaType.CASPER: "効率的な提案です。"
        }

        result = await agent.debate(others_thoughts, round_num=1)

        self.assertEqual(result.persona_type, PersonaType.BALTHASAR)
        self.assertEqual(result.round_number, 1)
        self.assertIsInstance(result.timestamp, datetime)
        self.assertIn("リスク", result.responses[PersonaType.MELCHIOR])

    async def test_debate_includes_others_thoughts_in_context(self):
        """debateは他エージェントの思考をコンテキストに含める"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse, LLMRequest

        persona = Persona(
            type=PersonaType.CASPER,
            name="CASPER-3",
            base_prompt="効率性の視点から分析します。"
        )

        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content="反論",
            usage={"input_tokens": 150, "output_tokens": 75},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)

        others_thoughts = {
            PersonaType.MELCHIOR: "MELCHIORの思考",
            PersonaType.BALTHASAR: "BALTHASARの思考"
        }

        await agent.debate(others_thoughts, round_num=1)

        # sendが呼ばれたことを確認
        mock_client.send.assert_called_once()

        # user_promptに他エージェントの思考が含まれていることを確認
        call_args = mock_client.send.call_args
        request = call_args[0][0]
        self.assertIn("MELCHIOR", request.user_prompt)
        self.assertIn("BALTHASAR", request.user_prompt)


class TestAgentVote(unittest.IsolatedAsyncioTestCase):
    """Agent.voteメソッドのテスト"""

    async def test_vote_approve(self):
        """voteメソッドはAPPROVE投票を生成できる"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="論理と科学の視点から分析します。"
        )

        # APPROVE投票を返すようモック
        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content='{"vote": "APPROVE", "reason": "論理的に問題ありません。"}',
            usage={"input_tokens": 200, "output_tokens": 50},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)
        result = await agent.vote("これまでの議論のコンテキスト")

        self.assertEqual(result.persona_type, PersonaType.MELCHIOR)
        self.assertEqual(result.vote, Vote.APPROVE)
        self.assertIn("論理的", result.reason)

    async def test_vote_deny(self):
        """voteメソッドはDENY投票を生成できる"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse

        persona = Persona(
            type=PersonaType.BALTHASAR,
            name="BALTHASAR-2",
            base_prompt="リスク回避の視点から分析します。"
        )

        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content='{"vote": "DENY", "reason": "重大なリスクがあります。"}',
            usage={"input_tokens": 200, "output_tokens": 50},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)
        result = await agent.vote("これまでの議論のコンテキスト")

        self.assertEqual(result.vote, Vote.DENY)
        self.assertIn("リスク", result.reason)

    async def test_vote_conditional(self):
        """voteメソッドはCONDITIONAL投票と条件を生成できる"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse

        persona = Persona(
            type=PersonaType.CASPER,
            name="CASPER-3",
            base_prompt="効率性の視点から分析します。"
        )

        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content='{"vote": "CONDITIONAL", "reason": "条件付きで承認します。", "conditions": ["条件1", "条件2"]}',
            usage={"input_tokens": 200, "output_tokens": 75},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)
        result = await agent.vote("これまでの議論のコンテキスト")

        self.assertEqual(result.vote, Vote.CONDITIONAL)
        self.assertIsNotNone(result.conditions)
        self.assertEqual(len(result.conditions), 2)
        self.assertIn("条件1", result.conditions)

    async def test_vote_handles_invalid_json(self):
        """voteメソッドは不正なJSONを適切に処理する"""
        from magi.agents.agent import Agent
        from magi.agents.persona import Persona
        from magi.llm.client import LLMClient, LLMResponse

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="論理と科学の視点から分析します。"
        )

        # 不正なJSONを返すようモック
        mock_client = MagicMock(spec=LLMClient)
        mock_client.send = AsyncMock(return_value=LLMResponse(
            content="これは有効なJSONではありません。APPROVE します。",
            usage={"input_tokens": 200, "output_tokens": 50},
            model="claude-sonnet-4-20250514"
        ))

        agent = Agent(persona=persona, llm_client=mock_client)
        result = await agent.vote("コンテキスト")

        # フォールバックとしてCONDITIONALになることを確認
        self.assertEqual(result.vote, Vote.CONDITIONAL)
        self.assertIn("パース失敗", result.reason)


if __name__ == '__main__':
    unittest.main()
