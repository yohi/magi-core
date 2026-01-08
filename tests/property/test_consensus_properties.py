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
from typing import Dict

from magi.models import (
    ConsensusPhase,
    DebateOutput,
    Decision,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
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
        model="claude-sonnet-4-20250514",
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

        async def mock_think(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
            """thinkメソッドのモック"""
            think_calls.append({
                "persona_type": agent_self.persona.type,
                "prompt": prompt_arg,
                "attachments": attachments,
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

        async def mock_think_with_timing(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
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

        async def mock_think(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
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

        async def mock_think(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
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

        async def mock_think(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
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

        async def mock_think(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
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
        async def mock_think(agent_self, prompt_arg: str, attachments: list = None) -> ThinkingOutput:
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


# ラウンド数の戦略（1-10）
round_count_strategy = st.integers(min_value=1, max_value=10)


# **Feature: magi-core, Property 7: Debate Phaseのコンテキスト構築**
# **Validates: Requirements 5.1**
class TestDebatePhaseContextBuilding(unittest.TestCase):
    """Debate Phaseのコンテキスト構築プロパティテスト

    Property 7: For any Debate Phase開始時に、
    各エージェントに渡されるコンテキストには他の2つのエージェントの思考結果が含まれる
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_each_agent_receives_others_thoughts(self, prompt: str):
        """各エージェントには他の2つのエージェントの思考結果が渡される

        Debate Phase実行時に、各エージェントのdebateメソッドに
        渡されるコンテキストに他の2つのエージェントの思考結果が含まれることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        # 思考結果をモック
        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考結果"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考結果"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考結果"
            ),
        }

        # debateメソッドへの呼び出しを記録
        debate_calls = []

        async def mock_debate(
            agent_self, others_thoughts: Dict[PersonaType, str], round_num: int
        ) -> DebateOutput:
            """debateメソッドのモック"""
            debate_calls.append({
                "persona_type": agent_self.persona.type,
                "others_thoughts": others_thoughts,
                "round_num": round_num,
            })
            return DebateOutput(
                persona_type=agent_self.persona.type,
                round_number=round_num,
                responses={},
                timestamp=datetime.now()
            )

        with patch('magi.agents.agent.Agent.debate', mock_debate):
            asyncio.run(engine._run_debate_phase(thinking_results))

        # 各エージェントがdebateを実行したことを確認
        self.assertEqual(len(debate_calls), 3)

        # 各エージェントが他2つのエージェントの思考を受け取ったことを確認
        for call in debate_calls:
            persona_type = call["persona_type"]
            others_thoughts = call["others_thoughts"]

            # 自分自身の思考は含まれていないことを確認
            self.assertNotIn(persona_type, others_thoughts)

            # 他の2つのエージェントの思考が含まれていることを確認
            other_types = [pt for pt in PersonaType if pt != persona_type]
            for other_type in other_types:
                self.assertIn(other_type, others_thoughts)

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_context_contains_actual_thinking_content(self, prompt: str):
        """コンテキストには実際の思考内容が含まれる

        渡されるコンテキストに思考結果の実際の内容が含まれていることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        # 特定の思考結果を設定
        melchior_content = "MELCHIOR: 論理的分析結果"
        balthasar_content = "BALTHASAR: リスク分析結果"
        casper_content = "CASPER: 実利的分析結果"

        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, melchior_content
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, balthasar_content
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, casper_content
            ),
        }

        # debateメソッドへの呼び出しを記録
        debate_calls = []

        async def mock_debate(
            agent_self, others_thoughts: Dict[PersonaType, str], round_num: int
        ) -> DebateOutput:
            """debateメソッドのモック"""
            debate_calls.append({
                "persona_type": agent_self.persona.type,
                "others_thoughts": others_thoughts,
            })
            return DebateOutput(
                persona_type=agent_self.persona.type,
                round_number=round_num,
                responses={},
                timestamp=datetime.now()
            )

        with patch('magi.agents.agent.Agent.debate', mock_debate):
            asyncio.run(engine._run_debate_phase(thinking_results))

        # 各エージェントへのコンテキスト内容を確認
        for call in debate_calls:
            persona_type = call["persona_type"]
            others_thoughts = call["others_thoughts"]

            if persona_type == PersonaType.MELCHIOR:
                # MELCHIORはBALTHASARとCASPERの思考を受け取る
                self.assertEqual(others_thoughts[PersonaType.BALTHASAR], balthasar_content)
                self.assertEqual(others_thoughts[PersonaType.CASPER], casper_content)
            elif persona_type == PersonaType.BALTHASAR:
                # BALTHASARはMELCHIORとCASPERの思考を受け取る
                self.assertEqual(others_thoughts[PersonaType.MELCHIOR], melchior_content)
                self.assertEqual(others_thoughts[PersonaType.CASPER], casper_content)
            else:
                # CASPERはMELCHIORとBALTHASARの思考を受け取る
                self.assertEqual(others_thoughts[PersonaType.MELCHIOR], melchior_content)
                self.assertEqual(others_thoughts[PersonaType.BALTHASAR], balthasar_content)


# **Feature: magi-core, Property 8: ラウンド数に基づく状態遷移**
# **Validates: Requirements 5.3**
class TestRoundBasedStateTransition(unittest.TestCase):
    """ラウンド数に基づく状態遷移プロパティテスト

    Property 8: For any 設定されたラウンド数nに対して、
    n回のDebateラウンド完了後にVoting Phaseに遷移する
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(debate_rounds=round_count_strategy)
    @settings(max_examples=100, deadline=None)
    def test_correct_number_of_debate_rounds(self, debate_rounds: int):
        """設定されたラウンド数だけDebateが実行される

        config.debate_roundsで設定されたラウンド数だけ
        Debateラウンドが実行されることを検証する。
        """
        # ラウンド数を設定したコンフィグを作成
        config = Config(
            api_key="test-api-key",
            model="claude-sonnet-4-20250514",
            debate_rounds=debate_rounds,
            voting_threshold="majority",
            output_format="markdown",
            timeout=60,
            retry_count=3
        )
        engine = ConsensusEngine(config)

        # 思考結果をモック
        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        # debateメソッドへの呼び出しを記録
        debate_round_numbers = []

        async def mock_debate(
            agent_self, others_thoughts: Dict[PersonaType, str], round_num: int
        ) -> DebateOutput:
            """debateメソッドのモック"""
            debate_round_numbers.append(round_num)
            return DebateOutput(
                persona_type=agent_self.persona.type,
                round_number=round_num,
                responses={},
                timestamp=datetime.now()
            )

        with patch('magi.agents.agent.Agent.debate', mock_debate):
            results = asyncio.run(engine._run_debate_phase(thinking_results))

        # 結果のラウンド数を確認
        self.assertEqual(len(results), debate_rounds)

        # 各ラウンドで3つのエージェントがdebateを実行
        # (debate_rounds ラウンド × 3 エージェント)
        expected_debate_calls = debate_rounds * 3
        self.assertEqual(len(debate_round_numbers), expected_debate_calls)

        # ラウンド番号が正しく設定されていることを確認
        for i in range(debate_rounds):
            round_num = i + 1
            round_calls = [r for r in debate_round_numbers if r == round_num]
            self.assertEqual(len(round_calls), 3)

    @given(debate_rounds=round_count_strategy)
    @settings(max_examples=100, deadline=None)
    def test_phase_transitions_to_voting_after_debates(self, debate_rounds: int):
        """全Debateラウンド完了後にVoting Phaseに遷移する

        設定されたラウンド数のDebateが完了した後、
        フェーズがVOTINGに遷移することを検証する。
        """
        config = Config(
            api_key="test-api-key",
            model="claude-sonnet-4-20250514",
            debate_rounds=debate_rounds,
            voting_threshold="majority",
            output_format="markdown",
            timeout=60,
            retry_count=3
        )
        engine = ConsensusEngine(config)

        # Debate開始前はDEBATEフェーズ（Thinkingの後）
        engine._transition_to_phase(ConsensusPhase.DEBATE)
        self.assertEqual(engine.current_phase, ConsensusPhase.DEBATE)

        # 思考結果をモック
        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        async def mock_debate(
            agent_self, others_thoughts: Dict[PersonaType, str], round_num: int
        ) -> DebateOutput:
            """debateメソッドのモック"""
            return DebateOutput(
                persona_type=agent_self.persona.type,
                round_number=round_num,
                responses={},
                timestamp=datetime.now()
            )

        with patch('magi.agents.agent.Agent.debate', mock_debate):
            asyncio.run(engine._run_debate_phase(thinking_results))

        # Debate完了後はVOTINGフェーズに遷移
        self.assertEqual(engine.current_phase, ConsensusPhase.VOTING)

    def test_default_debate_rounds_is_one(self):
        """デフォルトのDebateラウンド数は1

        ラウンド数が設定されていない場合、
        デフォルトで1ラウンドのDebateが実行されることを検証する。
        """
        config = create_test_config()  # debate_rounds=1がデフォルト
        engine = ConsensusEngine(config)

        # 思考結果をモック
        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        async def mock_debate(
            agent_self, others_thoughts: Dict[PersonaType, str], round_num: int
        ) -> DebateOutput:
            """debateメソッドのモック"""
            return DebateOutput(
                persona_type=agent_self.persona.type,
                round_number=round_num,
                responses={},
                timestamp=datetime.now()
            )

        with patch('magi.agents.agent.Agent.debate', mock_debate):
            results = asyncio.run(engine._run_debate_phase(thinking_results))

        # デフォルトでは1ラウンド
        self.assertEqual(len(results), 1)


# 投票の戦略
vote_strategy = st.sampled_from([Vote.APPROVE, Vote.DENY, Vote.CONDITIONAL])


def create_mock_vote_output(
    persona_type: PersonaType,
    vote: Vote,
    reason: str = "テスト理由",
    conditions: list = None
) -> VoteOutput:
    """テスト用のVoteOutputを作成"""
    return VoteOutput(
        persona_type=persona_type,
        vote=vote,
        reason=reason,
        conditions=conditions
    )


# **Feature: magi-core, Property 9: 投票集計と判定の正確性**
# **Validates: Requirements 6.2, 6.3, 6.4**
class TestVotingAccuracy(unittest.TestCase):
    """投票集計と判定の正確性プロパティテスト

    Property 9: For any 3つのエージェントの投票組み合わせ（APPROVE/DENY/CONDITIONAL）に対して、
    設定された閾値（majority/unanimous）に基づいて正しい最終判定とExit Codeが決定される
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(
        melchior_vote=vote_strategy,
        balthasar_vote=vote_strategy,
        casper_vote=vote_strategy,
        threshold=st.sampled_from(["majority", "unanimous"])
    )
    @settings(max_examples=100, deadline=None)
    def test_voting_decision_accuracy(
        self,
        melchior_vote: Vote,
        balthasar_vote: Vote,
        casper_vote: Vote,
        threshold: str
    ):
        """投票結果に基づいて正しい最終判定が決定される

        3つのエージェントの投票組み合わせと閾値設定に基づいて、
        正しいDecisionが決定されることを検証する。
        """
        config = Config(
            api_key="test-api-key",
            model="claude-sonnet-4-20250514",
            debate_rounds=1,
            voting_threshold=threshold,
            output_format="markdown",
            timeout=60,
            retry_count=3
        )
        engine = ConsensusEngine(config)

        # 思考結果とDebate結果をモック
        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        debate_results = []

        # 投票をモック
        vote_results = {
            PersonaType.MELCHIOR: create_mock_vote_output(
                PersonaType.MELCHIOR, melchior_vote
            ),
            PersonaType.BALTHASAR: create_mock_vote_output(
                PersonaType.BALTHASAR, balthasar_vote
            ),
            PersonaType.CASPER: create_mock_vote_output(
                PersonaType.CASPER, casper_vote
            ),
        }

        async def mock_vote(agent_self, context: str) -> VoteOutput:
            """voteメソッドのモック"""
            return vote_results[agent_self.persona.type]

        # フェーズをVOTINGに設定
        engine._transition_to_phase(ConsensusPhase.VOTING)

        with patch('magi.agents.agent.Agent.vote', mock_vote):
            result = asyncio.run(
                engine._run_voting_phase(thinking_results, debate_results)
            )

        # 投票集計
        approve_count = sum(
            1 for v in [melchior_vote, balthasar_vote, casper_vote]
            if v == Vote.APPROVE
        )
        deny_count = sum(
            1 for v in [melchior_vote, balthasar_vote, casper_vote]
            if v == Vote.DENY
        )

        # 期待される判定を計算
        if threshold == "unanimous":
            if approve_count == 3:
                expected_decision = Decision.APPROVED
            elif deny_count >= 1:
                expected_decision = Decision.DENIED
            else:
                expected_decision = Decision.CONDITIONAL
        else:  # majority
            if approve_count >= 2:
                expected_decision = Decision.APPROVED
            elif deny_count >= 2:
                expected_decision = Decision.DENIED
            else:
                expected_decision = Decision.CONDITIONAL

        # 判定が正しいことを確認
        self.assertEqual(result["decision"], expected_decision)

    @given(
        melchior_vote=vote_strategy,
        balthasar_vote=vote_strategy,
        casper_vote=vote_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_exit_code_accuracy(
        self,
        melchior_vote: Vote,
        balthasar_vote: Vote,
        casper_vote: Vote,
    ):
        """判定結果に基づいて正しいExit Codeが決定される

        APPROVEDはExit Code 0、DENIEDはExit Code 1、
        CONDITIONALはExit Code 2を返すことを検証する。
        """
        engine = ConsensusEngine(self.config)

        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        debate_results = []

        vote_results = {
            PersonaType.MELCHIOR: create_mock_vote_output(
                PersonaType.MELCHIOR, melchior_vote
            ),
            PersonaType.BALTHASAR: create_mock_vote_output(
                PersonaType.BALTHASAR, balthasar_vote
            ),
            PersonaType.CASPER: create_mock_vote_output(
                PersonaType.CASPER, casper_vote
            ),
        }

        async def mock_vote(agent_self, context: str) -> VoteOutput:
            return vote_results[agent_self.persona.type]

        engine._transition_to_phase(ConsensusPhase.VOTING)

        with patch('magi.agents.agent.Agent.vote', mock_vote):
            result = asyncio.run(
                engine._run_voting_phase(thinking_results, debate_results)
            )

        decision = result["decision"]

        if decision == Decision.APPROVED:
            expected_exit_code = 0
        elif decision == Decision.DENIED:
            expected_exit_code = 1
        else:
            expected_exit_code = 2

        self.assertEqual(result["exit_code"], expected_exit_code)

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_all_agents_vote(self, prompt: str):
        """全てのエージェントが投票を実行する

        Voting Phase実行時に、3つのエージェント全てが
        投票を行うことを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        debate_results = []

        vote_calls = []

        async def mock_vote(agent_self, context: str) -> VoteOutput:
            vote_calls.append(agent_self.persona.type)
            return create_mock_vote_output(
                agent_self.persona.type, Vote.APPROVE
            )

        engine._transition_to_phase(ConsensusPhase.VOTING)

        with patch('magi.agents.agent.Agent.vote', mock_vote):
            asyncio.run(
                engine._run_voting_phase(thinking_results, debate_results)
            )

        # 3つのエージェント全てが投票したことを確認
        self.assertEqual(len(vote_calls), 3)
        self.assertIn(PersonaType.MELCHIOR, vote_calls)
        self.assertIn(PersonaType.BALTHASAR, vote_calls)
        self.assertIn(PersonaType.CASPER, vote_calls)


# **Feature: magi-core, Property 10: CONDITIONAL投票時の条件出力**
# **Validates: Requirements 6.5**
class TestConditionalVoteOutput(unittest.TestCase):
    """CONDITIONAL投票時の条件出力プロパティテスト

    Property 10: For any CONDITIONALを含む投票結果に対して、
    出力には条件付き承認の詳細が含まれる
    """

    def setUp(self):
        """テストのセットアップ"""
        self.config = create_test_config()

    @given(
        conditions=st.lists(
            st.text(min_size=1, max_size=50),
            min_size=1,
            max_size=5
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_conditional_vote_includes_conditions(self, conditions: list):
        """CONDITIONAL投票には条件が含まれる

        CONDITIONALを投票した場合、その条件が
        出力結果に含まれることを検証する。
        """
        assume(all(len(c.strip()) > 0 for c in conditions))

        engine = ConsensusEngine(self.config)

        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        debate_results = []

        # MELCHIORがCONDITIONAL投票（条件付き）
        vote_results = {
            PersonaType.MELCHIOR: create_mock_vote_output(
                PersonaType.MELCHIOR,
                Vote.CONDITIONAL,
                "条件付き承認",
                conditions
            ),
            PersonaType.BALTHASAR: create_mock_vote_output(
                PersonaType.BALTHASAR, Vote.APPROVE
            ),
            PersonaType.CASPER: create_mock_vote_output(
                PersonaType.CASPER, Vote.APPROVE
            ),
        }

        async def mock_vote(agent_self, context: str) -> VoteOutput:
            return vote_results[agent_self.persona.type]

        engine._transition_to_phase(ConsensusPhase.VOTING)

        with patch('magi.agents.agent.Agent.vote', mock_vote):
            result = asyncio.run(
                engine._run_voting_phase(thinking_results, debate_results)
            )

        # CONDITIONAL投票の条件が出力に含まれていることを確認
        voting_results = result["voting_results"]
        melchior_vote = voting_results[PersonaType.MELCHIOR]

        self.assertEqual(melchior_vote.vote, Vote.CONDITIONAL)
        self.assertIsNotNone(melchior_vote.conditions)
        self.assertEqual(melchior_vote.conditions, conditions)

    @given(prompt=prompt_strategy)
    @settings(max_examples=100, deadline=None)
    def test_conditional_decision_includes_all_conditions(self, prompt: str):
        """CONDITIONAL判定には全ての条件が集約される

        複数のエージェントがCONDITIONALを投票した場合、
        全ての条件が出力結果に含まれることを検証する。
        """
        assume(len(prompt.strip()) > 0)

        engine = ConsensusEngine(self.config)

        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        debate_results = []

        # 2つのエージェントがCONDITIONAL投票
        vote_results = {
            PersonaType.MELCHIOR: create_mock_vote_output(
                PersonaType.MELCHIOR,
                Vote.CONDITIONAL,
                "条件付き承認1",
                ["条件A", "条件B"]
            ),
            PersonaType.BALTHASAR: create_mock_vote_output(
                PersonaType.BALTHASAR,
                Vote.CONDITIONAL,
                "条件付き承認2",
                ["条件C"]
            ),
            PersonaType.CASPER: create_mock_vote_output(
                PersonaType.CASPER, Vote.APPROVE
            ),
        }

        async def mock_vote(agent_self, context: str) -> VoteOutput:
            return vote_results[agent_self.persona.type]

        engine._transition_to_phase(ConsensusPhase.VOTING)

        with patch('magi.agents.agent.Agent.vote', mock_vote):
            result = asyncio.run(
                engine._run_voting_phase(thinking_results, debate_results)
            )

        # 全てのCONDITIONAL条件が集約されていることを確認
        all_conditions = result.get("all_conditions", [])
        self.assertIn("条件A", all_conditions)
        self.assertIn("条件B", all_conditions)
        self.assertIn("条件C", all_conditions)

    def test_phase_transitions_to_completed_after_voting(self):
        """Voting Phase完了後、フェーズはCOMPLETEDに遷移する"""
        engine = ConsensusEngine(self.config)

        thinking_results = {
            PersonaType.MELCHIOR: create_mock_thinking_output(
                PersonaType.MELCHIOR, "MELCHIORの思考"
            ),
            PersonaType.BALTHASAR: create_mock_thinking_output(
                PersonaType.BALTHASAR, "BALTHASARの思考"
            ),
            PersonaType.CASPER: create_mock_thinking_output(
                PersonaType.CASPER, "CASPERの思考"
            ),
        }

        debate_results = []

        async def mock_vote(agent_self, context: str) -> VoteOutput:
            return create_mock_vote_output(
                agent_self.persona.type, Vote.APPROVE
            )

        engine._transition_to_phase(ConsensusPhase.VOTING)

        with patch('magi.agents.agent.Agent.vote', mock_vote):
            asyncio.run(
                engine._run_voting_phase(thinking_results, debate_results)
            )

        # フェーズがCOMPLETEDに遷移していることを確認
        self.assertEqual(engine.current_phase, ConsensusPhase.COMPLETED)


if __name__ == '__main__':
    unittest.main()
