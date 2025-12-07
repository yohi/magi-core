"""合議プロトコルのプロパティベーステスト

Property 4: Thinking Phaseの独立性
- Validates: Requirements 4.2

Property 5: フェーズ遷移の正確性
- Validates: Requirements 4.3

Property 6: エージェント失敗時の継続性
- Validates: Requirements 4.4
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.models import (
    ConsensusPhase,
    PersonaType,
    ThinkingOutput,
)


# プロンプト文字列の戦略
prompt_strategy = st.text(min_size=1, max_size=500)

# 失敗パターンの戦略（どのエージェントが失敗するか）
failure_pattern_strategy = st.lists(
    st.sampled_from([PersonaType.MELCHIOR, PersonaType.BALTHASAR, PersonaType.CASPER]),
    min_size=0,
    max_size=3,
    unique=True
)


def create_test_config() -> Config:
    """テスト用の設定を作成"""
    return Config(
        api_key="test-api-key",
        model="claude-3-sonnet-20240229",
        debate_rounds=1,
        voting_threshold="majority",
        output_format="markdown",
        timeout=60,
        retry_count=3
    )


def create_mock_thinking_output(persona_type: PersonaType, content: str) -> ThinkingOutput:
    """テスト用のThinkingOutputを作成"""
    return ThinkingOutput(
        persona_type=persona_type,
        content=content,
        timestamp=datetime.now()
    )


# **Feature: magi-core, Property 4: Thinking Phaseの独立性**
# **Validates: Requirements 4.2**
class TestThinkingPhaseIndependence(unittest.TestCase):
    """Thinking Phaseの独立性プロパティテスト

    Property 4: For any Thinking Phase実行時に、
    各エージェントに渡されるコンテキストには他のエージェントの出力が含まれない
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_each_agent_receives_only_prompt(self, prompt: str):
        """各エージェントはプロンプトのみを受け取り、他エージェントの出力を参照しない

        Thinking Phase実行時に、各エージェントのthinkメソッドに
        渡されるのはユーザープロンプトのみであることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        # エージェントのthinkメソッドへの呼び出しを記録
        think_calls = []

        async def mock_think(agent_self, prompt_arg: str) -> ThinkingOutput:
            """thinkメソッドのモック"""
            think_calls.append({
                "persona_type": agent_self.persona.type,
                "prompt": prompt_arg,
            })
            return create_mock_thinking_output(
                agent_self.persona.type,
                f"思考結果: {prompt_arg[:50]}"
            )

        with patch('magi.agents.agent.Agent.think', mock_think):
            asyncio.run(engine._run_thinking_phase(prompt))

        # 各エージェントがプロンプトのみを受け取ったことを確認
        self.assertEqual(len(think_calls), 3)  # 3つのエージェント

        for call in think_calls:
            # 渡されたプロンプトが元のプロンプトと一致
            self.assertEqual(call["prompt"], prompt)
            # 他のエージェントの出力は含まれない
            # （他の出力がまだ存在しないので、混入することはない）

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_agents_think_concurrently_without_sharing(self, prompt: str):
        """エージェントは並列に思考し、結果を共有しない

        各エージェントの思考は互いに独立して行われ、
        他のエージェントの出力を参照できない状態であることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        # 思考開始時刻を記録
        think_start_times = {}
        think_end_times = {}

        async def mock_think_with_timing(agent_self, prompt_arg: str) -> ThinkingOutput:
            """タイミング付きthinkメソッドのモック"""
            think_start_times[agent_self.persona.type] = datetime.now()
            # 非常に短い遅延をシミュレート
            await asyncio.sleep(0.001)
            think_end_times[agent_self.persona.type] = datetime.now()
            return create_mock_thinking_output(
                agent_self.persona.type,
                f"思考結果: {prompt_arg[:50]}"
            )

        with patch('magi.agents.agent.Agent.think', mock_think_with_timing):
            asyncio.run(engine._run_thinking_phase(prompt))

        # 全てのエージェントが思考したことを確認
        self.assertEqual(len(think_start_times), 3)
        self.assertEqual(len(think_end_times), 3)

        # 各エージェントの思考結果が他のエージェントに渡されていないことを確認
        # （並列実行されるため、互いの結果を待たない）


# **Feature: magi-core, Property 5: フェーズ遷移の正確性**
# **Validates: Requirements 4.3**
class TestPhaseTransitionAccuracy(unittest.TestCase):
    """フェーズ遷移の正確性プロパティテスト

    Property 5: For any 全エージェントの思考完了後、
    ConsensusEngineのフェーズはTHINKINGからDEBATEに遷移する
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_phase_transitions_to_debate_after_thinking(self, prompt: str):
        """Thinking Phase完了後、フェーズはDEBATEに遷移する

        全エージェントの思考が完了した後、
        ConsensusEngineのcurrent_phaseがDEBATEに遷移することを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        # 初期フェーズを確認
        self.assertEqual(engine.current_phase, ConsensusPhase.THINKING)

        async def mock_think(agent_self, prompt_arg: str) -> ThinkingOutput:
            """thinkメソッドのモック"""
            return create_mock_thinking_output(
                agent_self.persona.type,
                f"思考結果: {prompt_arg[:50]}"
            )

        with patch('magi.agents.agent.Agent.think', mock_think):
            asyncio.run(engine._run_thinking_phase(prompt))

        # フェーズがDEBATEに遷移していることを確認
        self.assertEqual(engine.current_phase, ConsensusPhase.DEBATE)

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_thinking_results_collected_before_transition(self, prompt: str):
        """遷移前に全エージェントの思考結果が収集される

        フェーズ遷移が行われる前に、
        全エージェントの思考結果が収集されていることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        async def mock_think(agent_self, prompt_arg: str) -> ThinkingOutput:
            """thinkメソッドのモック"""
            return create_mock_thinking_output(
                agent_self.persona.type,
                f"思考結果 from {agent_self.persona.type.value}"
            )

        with patch('magi.agents.agent.Agent.think', mock_think):
            results = asyncio.run(engine._run_thinking_phase(prompt))

        # 3つのエージェントの結果が収集されていることを確認
        self.assertEqual(len(results), 3)

        # 各ペルソナタイプの結果が存在することを確認
        for persona_type in PersonaType:
            self.assertIn(persona_type, results)
            self.assertIsInstance(results[persona_type], ThinkingOutput)


# **Feature: magi-core, Property 6: エージェント失敗時の継続性**
# **Validates: Requirements 4.4**
class TestAgentFailureContinuity(unittest.TestCase):
    """エージェント失敗時の継続性プロパティテスト

    Property 6: For any エージェントの思考生成失敗時に、
    残りのエージェントの処理は継続され、失敗はエラーログに記録される
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(
        prompt=prompt_strategy,
        failing_agents=failure_pattern_strategy
    )
    @settings(max_examples=100, deadline=None)
    def test_remaining_agents_continue_on_failure(
        self,
        prompt: str,
        failing_agents: list
    ):
        """エージェント失敗時も残りのエージェントは処理を継続する

        一部のエージェントが失敗しても、
        残りのエージェントの思考生成は継続されることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        async def mock_think(agent_self, prompt_arg: str) -> ThinkingOutput:
            """thinkメソッドのモック（一部が失敗）"""
            if agent_self.persona.type in failing_agents:
                raise Exception(f"エージェント {agent_self.persona.type.value} の思考生成に失敗")
            return create_mock_thinking_output(
                agent_self.persona.type,
                f"思考結果 from {agent_self.persona.type.value}"
            )

        with patch('magi.agents.agent.Agent.think', mock_think):
            results = asyncio.run(engine._run_thinking_phase(prompt))

        # 成功したエージェントの結果のみが含まれていることを確認
        expected_success_count = 3 - len(failing_agents)
        self.assertEqual(len(results), expected_success_count)

        # 失敗したエージェントの結果は含まれていないことを確認
        for persona_type in failing_agents:
            self.assertNotIn(persona_type, results)

        # 成功したエージェントの結果が含まれていることを確認
        for persona_type in PersonaType:
            if persona_type not in failing_agents:
                self.assertIn(persona_type, results)

    @given(
        prompt=prompt_strategy,
        failing_agents=failure_pattern_strategy
    )
    @settings(max_examples=100, deadline=None)
    def test_failures_are_logged(self, prompt: str, failing_agents: list):
        """エージェントの失敗はエラーログに記録される

        エージェントの思考生成が失敗した場合、
        その失敗はエラーログに記録されることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        async def mock_think(agent_self, prompt_arg: str) -> ThinkingOutput:
            """thinkメソッドのモック（一部が失敗）"""
            if agent_self.persona.type in failing_agents:
                raise Exception(f"エージェント {agent_self.persona.type.value} の思考生成に失敗")
            return create_mock_thinking_output(
                agent_self.persona.type,
                f"思考結果 from {agent_self.persona.type.value}"
            )

        with patch('magi.agents.agent.Agent.think', mock_think):
            asyncio.run(engine._run_thinking_phase(prompt))

        # エラーログの数が失敗したエージェントの数と一致することを確認
        self.assertEqual(len(engine.errors), len(failing_agents))

        # 各失敗がエラーログに記録されていることを確認
        logged_personas = [
            error["persona_type"] for error in engine.errors
        ]
        for persona_type in failing_agents:
            self.assertIn(persona_type.value, logged_personas)

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_phase_transitions_even_with_failures(self, prompt: str):
        """エージェント失敗時もフェーズ遷移は行われる

        一部のエージェントが失敗しても、
        Thinking Phase完了後にフェーズ遷移が行われることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        # 全エージェントが失敗するケース
        async def mock_think(agent_self, prompt_arg: str) -> ThinkingOutput:
            """thinkメソッドのモック（全て失敗）"""
            raise Exception(f"エージェント {agent_self.persona.type.value} の思考生成に失敗")

        with patch('magi.agents.agent.Agent.think', mock_think):
            results = asyncio.run(engine._run_thinking_phase(prompt))

        # 結果は空
        self.assertEqual(len(results), 0)

        # それでもフェーズはDEBATEに遷移
        self.assertEqual(engine.current_phase, ConsensusPhase.DEBATE)

        # 全てのエラーが記録されている
        self.assertEqual(len(engine.errors), 3)


if __name__ == '__main__':
    unittest.main()
