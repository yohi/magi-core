"""
OutputFormatterのユニットテスト

出力フォーマッタの機能を検証する
"""

import json
import unittest
from datetime import datetime

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


class TestOutputFormat(unittest.TestCase):
    """OutputFormat enumのテスト"""

    def test_json_format_value(self):
        """JSON形式の値が正しいこと"""
        self.assertEqual(OutputFormat.JSON.value, "json")

    def test_markdown_format_value(self):
        """Markdown形式の値が正しいこと"""
        self.assertEqual(OutputFormat.MARKDOWN.value, "markdown")


class TestOutputFormatter(unittest.TestCase):
    """OutputFormatterクラスのテスト"""

    def setUp(self):
        """テスト用のConsensusResultを作成"""
        self.formatter = OutputFormatter()
        self.timestamp = datetime(2025, 12, 7, 12, 0, 0)
        
        # Thinking結果
        self.thinking_results = {
            PersonaType.MELCHIOR.value: ThinkingOutput(
                persona_type=PersonaType.MELCHIOR,
                content="論理的な分析結果です。",
                timestamp=self.timestamp,
            ),
            PersonaType.BALTHASAR.value: ThinkingOutput(
                persona_type=PersonaType.BALTHASAR,
                content="リスク分析の結果です。",
                timestamp=self.timestamp,
            ),
            PersonaType.CASPER.value: ThinkingOutput(
                persona_type=PersonaType.CASPER,
                content="効率性の観点からの分析です。",
                timestamp=self.timestamp,
            ),
        }
        
        # Debate結果
        self.debate_results = [
            DebateRound(
                round_number=1,
                outputs={
                    PersonaType.MELCHIOR: DebateOutput(
                        persona_type=PersonaType.MELCHIOR,
                        round_number=1,
                        responses={
                            PersonaType.BALTHASAR: "BALTHASARへの反論",
                            PersonaType.CASPER: "CASPERへの反論",
                        },
                        timestamp=self.timestamp,
                    ),
                    PersonaType.BALTHASAR: DebateOutput(
                        persona_type=PersonaType.BALTHASAR,
                        round_number=1,
                        responses={
                            PersonaType.MELCHIOR: "MELCHIORへの反論",
                            PersonaType.CASPER: "CASPERへの反論",
                        },
                        timestamp=self.timestamp,
                    ),
                    PersonaType.CASPER: DebateOutput(
                        persona_type=PersonaType.CASPER,
                        round_number=1,
                        responses={
                            PersonaType.MELCHIOR: "MELCHIORへの反論",
                            PersonaType.BALTHASAR: "BALTHASARへの反論",
                        },
                        timestamp=self.timestamp,
                    ),
                },
                timestamp=self.timestamp,
            )
        ]
        
        # Voting結果
        self.voting_results = {
            PersonaType.MELCHIOR: VoteOutput(
                persona_type=PersonaType.MELCHIOR,
                vote=Vote.APPROVE,
                reason="論理的に正しいため承認",
            ),
            PersonaType.BALTHASAR: VoteOutput(
                persona_type=PersonaType.BALTHASAR,
                vote=Vote.APPROVE,
                reason="リスクが許容範囲内",
            ),
            PersonaType.CASPER: VoteOutput(
                persona_type=PersonaType.CASPER,
                vote=Vote.APPROVE,
                reason="効率的な解決策",
            ),
        }
        
        self.consensus_result = ConsensusResult(
            thinking_results=self.thinking_results,
            debate_results=self.debate_results,
            voting_results=self.voting_results,
            final_decision=Decision.APPROVED,
            exit_code=0,
        )

    def test_format_json_returns_valid_json(self):
        """JSON形式で有効なJSONが返されること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        
        # JSONとしてパース可能であること
        parsed = json.loads(output)
        self.assertIsInstance(parsed, dict)

    def test_format_json_contains_thinking_results(self):
        """JSON出力に思考結果が含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        self.assertIn("thinking_results", parsed)
        self.assertIn("melchior", parsed["thinking_results"])
        self.assertIn("balthasar", parsed["thinking_results"])
        self.assertIn("casper", parsed["thinking_results"])

    def test_format_json_contains_debate_results(self):
        """JSON出力に議論結果が含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        self.assertIn("debate_results", parsed)
        self.assertIsInstance(parsed["debate_results"], list)
        self.assertEqual(len(parsed["debate_results"]), 1)

    def test_format_json_contains_voting_results(self):
        """JSON出力に投票結果が含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        self.assertIn("voting_results", parsed)
        self.assertIn("melchior", parsed["voting_results"])
        self.assertIn("balthasar", parsed["voting_results"])
        self.assertIn("casper", parsed["voting_results"])

    def test_format_json_contains_final_decision(self):
        """JSON出力に最終判定が含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        self.assertIn("final_decision", parsed)
        self.assertEqual(parsed["final_decision"], "approved")

    def test_format_json_contains_exit_code(self):
        """JSON出力にExit Codeが含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.JSON)
        parsed = json.loads(output)
        
        self.assertIn("exit_code", parsed)
        self.assertEqual(parsed["exit_code"], 0)

    def test_format_markdown_returns_string(self):
        """Markdown形式で文字列が返されること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        self.assertIsInstance(output, str)
        self.assertTrue(len(output) > 0)

    def test_format_markdown_contains_thinking_section(self):
        """Markdown出力に思考セクションが含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        # 絵文字やカラーコードが含まれるため、主要なキーワードが含まれていることを確認
        self.assertIn("MAGI 合議結果", output)
        self.assertIn("Thinking Phase", output)
        self.assertIn("MELCHIOR", output)
        self.assertIn("BALTHASAR", output)
        self.assertIn("CASPER", output)

    def test_format_markdown_contains_debate_section(self):
        """Markdown出力に議論セクションが含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        self.assertIn("Debate Phase", output)

    def test_format_markdown_contains_voting_section(self):
        """Markdown出力に投票セクションが含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        self.assertIn("Voting Phase", output)
        self.assertIn("APPROVE", output)

    def test_format_markdown_contains_final_decision(self):
        """Markdown出力に最終判定が含まれること"""
        output = self.formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        self.assertIn("## 最終判定", output)
        self.assertIn("APPROVED", output)

    def test_format_markdown_plain_returns_string_without_colors(self):
        """Markdown形式(plain=True)で色や絵文字が含まれないこと"""
        plain_formatter = OutputFormatter(plain=True)
        output = plain_formatter.format(self.consensus_result, OutputFormat.MARKDOWN)
        
        self.assertIn("# MAGI 合議結果", output)
        self.assertIn("## Thinking Phase", output)
        self.assertIn("### MELCHIOR", output) # 絵文字なし
        self.assertNotIn("🔬", output)
        self.assertNotIn("\033[", output) # カラーコードなし

    def test_format_with_conditional_vote(self):
        """条件付き投票がある場合に条件が出力されること"""
        voting_results = {
            PersonaType.MELCHIOR: VoteOutput(
                persona_type=PersonaType.MELCHIOR,
                vote=Vote.APPROVE,
                reason="承認",
            ),
            PersonaType.BALTHASAR: VoteOutput(
                persona_type=PersonaType.BALTHASAR,
                vote=Vote.CONDITIONAL,
                reason="条件付き承認",
                conditions=["セキュリティレビュー", "負荷テスト"],
            ),
            PersonaType.CASPER: VoteOutput(
                persona_type=PersonaType.CASPER,
                vote=Vote.APPROVE,
                reason="承認",
            ),
        }
        
        result = ConsensusResult(
            thinking_results=self.thinking_results,
            debate_results=self.debate_results,
            voting_results=voting_results,
            final_decision=Decision.CONDITIONAL,
            exit_code=0,
            all_conditions=["セキュリティレビュー", "負荷テスト"],
        )
        
        # JSON形式
        json_output = self.formatter.format(result, OutputFormat.JSON)
        parsed = json.loads(json_output)
        self.assertIn("conditions", parsed)
        
        # Markdown形式
        md_output = self.formatter.format(result, OutputFormat.MARKDOWN)
        self.assertIn("セキュリティレビュー", md_output)
        self.assertIn("負荷テスト", md_output)

    def test_format_with_empty_debate_results(self):
        """議論結果が空の場合も正常に動作すること"""
        result = ConsensusResult(
            thinking_results=self.thinking_results,
            debate_results=[],
            voting_results=self.voting_results,
            final_decision=Decision.APPROVED,
            exit_code=0,
        )
        
        # JSON形式
        json_output = self.formatter.format(result, OutputFormat.JSON)
        parsed = json.loads(json_output)
        self.assertEqual(parsed["debate_results"], [])
        
        # Markdown形式
        md_output = self.formatter.format(result, OutputFormat.MARKDOWN)
        self.assertIsInstance(md_output, str)


if __name__ == "__main__":
    unittest.main()
