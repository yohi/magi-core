"""
出力フォーマットのプロパティテスト

**Feature: magi-core, Property 15: 出力フォーマット変換の正確性**
**Validates: Requirements 11.1, 11.2, 11.3**
"""

import json
import unittest
from datetime import datetime

from hypothesis import given, settings, strategies as st

from magi.models import (
    ConsensusResult,
    Decision,
    PersonaType,
    ThinkingOutput,
    VoteOutput,
    Vote,
    DebateRound,
    DebateOutput,
)
from magi.output.formatter import OutputFormat, OutputFormatter


# 戦略: PersonaTypeを生成
persona_type_strategy = st.sampled_from(list(PersonaType))

# 戦略: Voteを生成
vote_strategy = st.sampled_from(list(Vote))

# 戦略: Decisionを生成
decision_strategy = st.sampled_from(list(Decision))

# 戦略: ThinkingOutputを生成
@st.composite
def thinking_output_strategy(draw):
    """ThinkingOutputを生成"""
    return ThinkingOutput(
        persona_type=draw(persona_type_strategy),
        content=draw(st.text(min_size=1, max_size=500)),
        timestamp=datetime(2025, 12, 7, 12, 0, 0),
    )

# 戦略: VoteOutputを生成
@st.composite
def vote_output_strategy(draw):
    """VoteOutputを生成"""
    vote = draw(vote_strategy)
    conditions = None
    if vote == Vote.CONDITIONAL:
        conditions = draw(st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=3))
    
    return VoteOutput(
        persona_type=draw(persona_type_strategy),
        vote=vote,
        reason=draw(st.text(min_size=1, max_size=200)),
        conditions=conditions,
    )

# 戦略: DebateOutputを生成
@st.composite
def debate_output_strategy(draw, persona: PersonaType):
    """DebateOutputを生成"""
    other_personas = [p for p in PersonaType if p != persona]
    responses = {
        other: draw(st.text(min_size=1, max_size=200))
        for other in other_personas
    }
    
    return DebateOutput(
        persona_type=persona,
        round_number=draw(st.integers(min_value=1, max_value=10)),
        responses=responses,
        timestamp=datetime(2025, 12, 7, 12, 0, 0),
    )

# 戦略: DebateRoundを生成
@st.composite
def debate_round_strategy(draw, round_number: int = 1):
    """DebateRoundを生成"""
    outputs = {}
    for persona in PersonaType:
        outputs[persona] = draw(debate_output_strategy(persona))
        # ラウンド番号を統一
        outputs[persona] = DebateOutput(
            persona_type=persona,
            round_number=round_number,
            responses=outputs[persona].responses,
            timestamp=outputs[persona].timestamp,
        )
    
    return DebateRound(
        round_number=round_number,
        outputs=outputs,
        timestamp=datetime(2025, 12, 7, 12, 0, 0),
    )

# 戦略: ConsensusResultを生成
@st.composite
def consensus_result_strategy(draw):
    """ConsensusResultを生成"""
    # Thinking結果
    thinking_results = {}
    for persona in PersonaType:
        thinking_output = ThinkingOutput(
            persona_type=persona,
            content=draw(st.text(min_size=1, max_size=500)),
            timestamp=datetime(2025, 12, 7, 12, 0, 0),
        )
        thinking_results[persona.value] = thinking_output
    
    # Debate結果（0〜3ラウンド）
    num_rounds = draw(st.integers(min_value=0, max_value=3))
    debate_results = []
    for i in range(num_rounds):
        debate_results.append(draw(debate_round_strategy(i + 1)))
    
    # Voting結果
    voting_results = {}
    all_conditions = []
    for persona in PersonaType:
        vote = draw(vote_strategy)
        conditions = None
        if vote == Vote.CONDITIONAL:
            conditions = draw(st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=3))
            all_conditions.extend(conditions)
        
        voting_results[persona] = VoteOutput(
            persona_type=persona,
            vote=vote,
            reason=draw(st.text(min_size=1, max_size=200)),
            conditions=conditions,
        )
    
    decision = draw(decision_strategy)
    exit_code = 0 if decision == Decision.APPROVED else 1
    
    return ConsensusResult(
        thinking_results=thinking_results,
        debate_results=debate_results,
        voting_results=voting_results,
        final_decision=decision,
        exit_code=exit_code,
        all_conditions=all_conditions if all_conditions else None,
    )


class TestOutputFormattingProperty(unittest.TestCase):
    """Property 15: 出力フォーマット変換の正確性
    
    *For any* ConsensusResultと出力形式（JSON/Markdown）に対して、
    指定形式で有効な出力が生成され、必要な情報（思考、議論、投票結果）が含まれる
    """

    def setUp(self):
        """テストの準備"""
        self.formatter = OutputFormatter()

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_json_output_is_valid_json(self, result: ConsensusResult):
        """JSON形式で有効なJSONが生成されること"""
        output = self.formatter.format(result, OutputFormat.JSON)
        
        # JSONとしてパース可能であること
        parsed = json.loads(output)
        self.assertIsInstance(parsed, dict)

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_json_contains_all_required_fields(self, result: ConsensusResult):
        """JSON出力に全ての必須フィールドが含まれること"""
        output = self.formatter.format(result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        # 必須フィールドの存在確認
        self.assertIn("thinking_results", parsed)
        self.assertIn("debate_results", parsed)
        self.assertIn("voting_results", parsed)
        self.assertIn("final_decision", parsed)
        self.assertIn("exit_code", parsed)

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_json_thinking_results_complete(self, result: ConsensusResult):
        """JSON出力の思考結果が完全であること"""
        output = self.formatter.format(result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        thinking = parsed["thinking_results"]
        for persona in PersonaType:
            self.assertIn(persona.value, thinking)
            self.assertIn("content", thinking[persona.value])

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_json_voting_results_complete(self, result: ConsensusResult):
        """JSON出力の投票結果が完全であること"""
        output = self.formatter.format(result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        voting = parsed["voting_results"]
        for persona in PersonaType:
            self.assertIn(persona.value, voting)
            self.assertIn("vote", voting[persona.value])
            self.assertIn("reason", voting[persona.value])

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_markdown_output_is_non_empty_string(self, result: ConsensusResult):
        """Markdown形式で空でない文字列が生成されること"""
        output = self.formatter.format(result, OutputFormat.MARKDOWN)
        
        self.assertIsInstance(output, str)
        self.assertTrue(len(output) > 0)

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_markdown_contains_all_sections(self, result: ConsensusResult):
        """Markdown出力に全てのセクションが含まれること"""
        output = self.formatter.format(result, OutputFormat.MARKDOWN)
        
        # 必須セクションの存在確認
        self.assertIn("# MAGI 合議結果", output)
        self.assertIn("## Thinking Phase", output)
        self.assertIn("## Voting Phase", output)
        self.assertIn("## 最終判定", output)

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_markdown_contains_all_personas(self, result: ConsensusResult):
        """Markdown出力に全てのペルソナが含まれること"""
        output = self.formatter.format(result, OutputFormat.MARKDOWN)
        
        for persona in PersonaType:
            self.assertIn(persona.value.upper(), output)

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_conditional_vote_includes_conditions(self, result: ConsensusResult):
        """条件付き投票がある場合、条件が出力に含まれること"""
        # 条件がある場合のみチェック
        if result.all_conditions:
            json_output = self.formatter.format(result, OutputFormat.JSON)
            parsed = json.loads(json_output)
            
            self.assertIn("conditions", parsed)
            self.assertIsInstance(parsed["conditions"], list)

    @given(result=consensus_result_strategy())
    @settings(max_examples=100)
    def test_output_format_consistency(self, result: ConsensusResult):
        """同じ入力に対して同じ出力が生成されること"""
        json_output1 = self.formatter.format(result, OutputFormat.JSON)
        json_output2 = self.formatter.format(result, OutputFormat.JSON)
        
        md_output1 = self.formatter.format(result, OutputFormat.MARKDOWN)
        md_output2 = self.formatter.format(result, OutputFormat.MARKDOWN)
        
        self.assertEqual(json_output1, json_output2)
        self.assertEqual(md_output1, md_output2)


if __name__ == "__main__":
    unittest.main()
