"""ConsensusEngineのユニットテスト

Requirements:
    - 4.1: ユーザーがプロンプトを入力すると3つのエージェントに対して独立した思考生成を要求
    - 4.3: 全エージェントが思考を完了すると3つの独立した思考結果を収集し次のフェーズに進む
    - 5.3: 設定されたラウンド数に達するとDebate Phaseを終了しVoting Phaseに移行
    - 6.1: Voting PhaseでAPPROVE、DENY、CONDITIONALのいずれかの投票を要求
    - 6.2: 全エージェントが投票を完了すると投票結果を集計し最終判定を決定
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from datetime import datetime

from magi.core.consensus import ConsensusEngine
from magi.core.context import ContextManager
from magi.agents.persona import PersonaManager
from magi.agents.agent import Agent
from magi.config.manager import Config
from magi.models import (
    ConsensusPhase,
    ConsensusResult,
    ThinkingOutput,
    DebateOutput,
    DebateRound,
    VoteOutput,
    Vote,
    Decision,
    PersonaType,
)


class TestConsensusEngineInit(unittest.TestCase):
    """ConsensusEngineの初期化テスト"""

    def test_init_with_config(self):
        """Configを指定して初期化できることを確認"""
        config = Config(
            api_key="test-api-key",
            debate_rounds=2,
            voting_threshold="unanimous"
        )

        engine = ConsensusEngine(config)

        self.assertIsInstance(engine.persona_manager, PersonaManager)
        self.assertIsInstance(engine.context_manager, ContextManager)
        self.assertEqual(engine.current_phase, ConsensusPhase.THINKING)
        self.assertEqual(engine.config.debate_rounds, 2)
        self.assertEqual(engine.config.voting_threshold, "unanimous")

    def test_initial_phase_is_thinking(self):
        """初期フェーズがTHINKINGであることを確認"""
        config = Config(api_key="test-api-key")
        engine = ConsensusEngine(config)

        self.assertEqual(engine.current_phase, ConsensusPhase.THINKING)


class TestConsensusEnginePhaseTransition(unittest.TestCase):
    """フェーズ遷移のテスト"""

    def setUp(self):
        """テストの前準備"""
        self.config = Config(
            api_key="test-api-key",
            debate_rounds=1,
            voting_threshold="majority"
        )
        self.engine = ConsensusEngine(self.config)

    def test_transition_from_thinking_to_debate(self):
        """THINKINGからDEBATEへの遷移を確認"""
        self.engine.current_phase = ConsensusPhase.THINKING
        self.engine._transition_to_phase(ConsensusPhase.DEBATE)

        self.assertEqual(self.engine.current_phase, ConsensusPhase.DEBATE)

    def test_transition_from_debate_to_voting(self):
        """DEBATEからVOTINGへの遷移を確認"""
        self.engine.current_phase = ConsensusPhase.DEBATE
        self.engine._transition_to_phase(ConsensusPhase.VOTING)

        self.assertEqual(self.engine.current_phase, ConsensusPhase.VOTING)

    def test_transition_from_voting_to_completed(self):
        """VOTINGからCOMPLETEDへの遷移を確認"""
        self.engine.current_phase = ConsensusPhase.VOTING
        self.engine._transition_to_phase(ConsensusPhase.COMPLETED)

        self.assertEqual(self.engine.current_phase, ConsensusPhase.COMPLETED)


class TestThinkingPhase(unittest.TestCase):
    """Thinking Phaseのテスト"""

    def setUp(self):
        """テストの前準備"""
        self.config = Config(api_key="test-api-key")
        self.engine = ConsensusEngine(self.config)

    def test_thinking_phase_calls_all_agents(self):
        """Thinking Phaseで3つのエージェント全てが呼び出されることを確認

        Requirements 4.1: 3つのエージェントに対して独立した思考生成を要求
        """
        # モックの設定
        mock_thinking_output = ThinkingOutput(
            persona_type=PersonaType.MELCHIOR,
            content="テスト思考内容",
            timestamp=datetime.now()
        )

        with patch.object(
            self.engine,
            '_create_agents',
            return_value={
                PersonaType.MELCHIOR: MagicMock(
                    think=AsyncMock(return_value=mock_thinking_output)
                ),
                PersonaType.BALTHASAR: MagicMock(
                    think=AsyncMock(return_value=ThinkingOutput(
                        persona_type=PersonaType.BALTHASAR,
                        content="BALTHASAR思考",
                        timestamp=datetime.now()
                    ))
                ),
                PersonaType.CASPER: MagicMock(
                    think=AsyncMock(return_value=ThinkingOutput(
                        persona_type=PersonaType.CASPER,
                        content="CASPER思考",
                        timestamp=datetime.now()
                    ))
                ),
            }
        ):
            result = asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            self.assertEqual(len(result), 3)
            self.assertIn(PersonaType.MELCHIOR, result)
            self.assertIn(PersonaType.BALTHASAR, result)
            self.assertIn(PersonaType.CASPER, result)

    def test_thinking_phase_returns_independent_outputs(self):
        """Thinking Phaseが各エージェントの独立した出力を返すことを確認

        Requirements 4.2: 各エージェントが他のエージェントの出力を参照できない状態で思考を生成
        """
        mock_agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.MELCHIOR,
                    content="MELCHIOR独立思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.BALTHASAR,
                    content="BALTHASAR独立思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.CASPER,
                    content="CASPER独立思考",
                    timestamp=datetime.now()
                ))
            ),
        }

        with patch.object(self.engine, '_create_agents', return_value=mock_agents):
            result = asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            # 各エージェントのthinkメソッドが同じプロンプトで呼ばれていることを確認
            for agent in mock_agents.values():
                agent.think.assert_called_once_with("テストプロンプト")

    def test_thinking_phase_transitions_to_debate(self):
        """Thinking Phase完了後にDEBATEフェーズに遷移することを確認

        Requirements 4.3: 全エージェントが思考を完了すると次のフェーズに進む
        """
        mock_agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.MELCHIOR,
                    content="思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.BALTHASAR,
                    content="思考",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.CASPER,
                    content="思考",
                    timestamp=datetime.now()
                ))
            ),
        }

        with patch.object(self.engine, '_create_agents', return_value=mock_agents):
            self.assertEqual(self.engine.current_phase, ConsensusPhase.THINKING)

            asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            # Thinking Phase実行後、フェーズがDEBATEに遷移していることを確認
            self.assertEqual(self.engine.current_phase, ConsensusPhase.DEBATE)

    def test_thinking_phase_continues_on_agent_failure(self):
        """エージェントが失敗しても他のエージェントの処理が継続されることを確認

        Requirements 4.4: エージェントの思考生成が失敗した場合、
        エラーを記録し残りのエージェントの処理を継続する
        """
        mock_agents = {
            PersonaType.MELCHIOR: MagicMock(
                think=AsyncMock(side_effect=Exception("MELCHIOR失敗"))
            ),
            PersonaType.BALTHASAR: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.BALTHASAR,
                    content="BALTHASAR成功",
                    timestamp=datetime.now()
                ))
            ),
            PersonaType.CASPER: MagicMock(
                think=AsyncMock(return_value=ThinkingOutput(
                    persona_type=PersonaType.CASPER,
                    content="CASPER成功",
                    timestamp=datetime.now()
                ))
            ),
        }

        with patch.object(self.engine, '_create_agents', return_value=mock_agents):
            result = asyncio.run(self.engine._run_thinking_phase("テストプロンプト"))

            # 失敗したエージェント以外の結果が返されることを確認
            self.assertEqual(len(result), 2)
            self.assertIn(PersonaType.BALTHASAR, result)
            self.assertIn(PersonaType.CASPER, result)
            self.assertNotIn(PersonaType.MELCHIOR, result)


class TestConsensusEngineAgentCreation(unittest.TestCase):
    """エージェント作成のテスト"""

    def setUp(self):
        """テストの前準備"""
        self.config = Config(api_key="test-api-key")
        self.engine = ConsensusEngine(self.config)

    def test_create_agents_returns_three_agents(self):
        """3つのエージェントが作成されることを確認"""
        with patch('magi.core.consensus.LLMClient'):
            agents = self.engine._create_agents()

            self.assertEqual(len(agents), 3)
            self.assertIn(PersonaType.MELCHIOR, agents)
            self.assertIn(PersonaType.BALTHASAR, agents)
            self.assertIn(PersonaType.CASPER, agents)

    def test_create_agents_with_correct_personas(self):
        """各エージェントが正しいペルソナで作成されることを確認"""
        with patch('magi.core.consensus.LLMClient'):
            agents = self.engine._create_agents()

            for persona_type, agent in agents.items():
                self.assertIsInstance(agent, Agent)
                self.assertEqual(agent.persona.type, persona_type)


if __name__ == '__main__':
    unittest.main()
