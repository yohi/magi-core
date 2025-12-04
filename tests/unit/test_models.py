"""
共通データモデルのユニットテスト

設計ドキュメントに基づいたデータモデルの検証
"""

import unittest
from datetime import datetime


class TestVoteEnum(unittest.TestCase):
    """Vote列挙型のテスト"""

    def test_vote_has_approve(self):
        """APPROVEが定義されていること"""
        from magi.models import Vote
        self.assertEqual(Vote.APPROVE.value, "approve")

    def test_vote_has_deny(self):
        """DENYが定義されていること"""
        from magi.models import Vote
        self.assertEqual(Vote.DENY.value, "deny")

    def test_vote_has_conditional(self):
        """CONDITIONALが定義されていること"""
        from magi.models import Vote
        self.assertEqual(Vote.CONDITIONAL.value, "conditional")


class TestDecisionEnum(unittest.TestCase):
    """Decision列挙型のテスト"""

    def test_decision_has_approved(self):
        """APPROVEDが定義されていること"""
        from magi.models import Decision
        self.assertEqual(Decision.APPROVED.value, "approved")

    def test_decision_has_denied(self):
        """DENIEDが定義されていること"""
        from magi.models import Decision
        self.assertEqual(Decision.DENIED.value, "denied")

    def test_decision_has_conditional(self):
        """CONDITIONALが定義されていること"""
        from magi.models import Decision
        self.assertEqual(Decision.CONDITIONAL.value, "conditional")


class TestVotingTally(unittest.TestCase):
    """VotingTally投票集計のテスト"""

    def test_voting_tally_creation(self):
        """VotingTallyが正しく作成されること"""
        from magi.models import VotingTally
        tally = VotingTally(approve_count=2, deny_count=1, conditional_count=0)
        self.assertEqual(tally.approve_count, 2)
        self.assertEqual(tally.deny_count, 1)
        self.assertEqual(tally.conditional_count, 0)

    def test_majority_approve_decision(self):
        """majority閾値で2票以上のAPPROVEでAPPROVEDになること"""
        from magi.models import VotingTally, Decision
        tally = VotingTally(approve_count=2, deny_count=1, conditional_count=0)
        decision = tally.get_decision("majority")
        self.assertEqual(decision, Decision.APPROVED)

    def test_majority_deny_decision(self):
        """majority閾値で2票以上のDENYでDENIEDになること"""
        from magi.models import VotingTally, Decision
        tally = VotingTally(approve_count=1, deny_count=2, conditional_count=0)
        decision = tally.get_decision("majority")
        self.assertEqual(decision, Decision.DENIED)

    def test_majority_conditional_decision(self):
        """majority閾値で過半数がない場合CONDITIONALになること"""
        from magi.models import VotingTally, Decision
        tally = VotingTally(approve_count=1, deny_count=1, conditional_count=1)
        decision = tally.get_decision("majority")
        self.assertEqual(decision, Decision.CONDITIONAL)

    def test_unanimous_approve_decision(self):
        """unanimous閾値で3票全てAPPROVEでAPPROVEDになること"""
        from magi.models import VotingTally, Decision
        tally = VotingTally(approve_count=3, deny_count=0, conditional_count=0)
        decision = tally.get_decision("unanimous")
        self.assertEqual(decision, Decision.APPROVED)

    def test_unanimous_deny_decision(self):
        """unanimous閾値で1票以上のDENYでDENIEDになること"""
        from magi.models import VotingTally, Decision
        tally = VotingTally(approve_count=2, deny_count=1, conditional_count=0)
        decision = tally.get_decision("unanimous")
        self.assertEqual(decision, Decision.DENIED)

    def test_unanimous_conditional_decision(self):
        """unanimous閾値でDENYがなくAPPROVEが3未満でCONDITIONALになること"""
        from magi.models import VotingTally, Decision
        tally = VotingTally(approve_count=2, deny_count=0, conditional_count=1)
        decision = tally.get_decision("unanimous")
        self.assertEqual(decision, Decision.CONDITIONAL)


class TestPersonaType(unittest.TestCase):
    """PersonaType列挙型のテスト"""

    def test_persona_type_has_melchior(self):
        """MELCHIORが定義されていること"""
        from magi.models import PersonaType
        self.assertEqual(PersonaType.MELCHIOR.value, "melchior")

    def test_persona_type_has_balthasar(self):
        """BALTHASARが定義されていること"""
        from magi.models import PersonaType
        self.assertEqual(PersonaType.BALTHASAR.value, "balthasar")

    def test_persona_type_has_casper(self):
        """CASPERが定義されていること"""
        from magi.models import PersonaType
        self.assertEqual(PersonaType.CASPER.value, "casper")


class TestConsensusPhase(unittest.TestCase):
    """ConsensusPhase列挙型のテスト"""

    def test_phase_has_thinking(self):
        """THINKINGが定義されていること"""
        from magi.models import ConsensusPhase
        self.assertEqual(ConsensusPhase.THINKING.value, "thinking")

    def test_phase_has_debate(self):
        """DEBATEが定義されていること"""
        from magi.models import ConsensusPhase
        self.assertEqual(ConsensusPhase.DEBATE.value, "debate")

    def test_phase_has_voting(self):
        """VOTINGが定義されていること"""
        from magi.models import ConsensusPhase
        self.assertEqual(ConsensusPhase.VOTING.value, "voting")

    def test_phase_has_completed(self):
        """COMPLETEDが定義されていること"""
        from magi.models import ConsensusPhase
        self.assertEqual(ConsensusPhase.COMPLETED.value, "completed")


class TestThinkingOutput(unittest.TestCase):
    """ThinkingOutputデータクラスのテスト"""

    def test_thinking_output_creation(self):
        """ThinkingOutputが正しく作成されること"""
        from magi.models import ThinkingOutput, PersonaType
        timestamp = datetime.now()
        output = ThinkingOutput(
            persona_type=PersonaType.MELCHIOR,
            content="思考内容のテスト",
            timestamp=timestamp
        )
        self.assertEqual(output.persona_type, PersonaType.MELCHIOR)
        self.assertEqual(output.content, "思考内容のテスト")
        self.assertEqual(output.timestamp, timestamp)

    def test_thinking_output_with_different_persona(self):
        """異なるペルソナタイプでThinkingOutputが作成できること"""
        from magi.models import ThinkingOutput, PersonaType
        timestamp = datetime.now()
        output = ThinkingOutput(
            persona_type=PersonaType.BALTHASAR,
            content="別の思考内容",
            timestamp=timestamp
        )
        self.assertEqual(output.persona_type, PersonaType.BALTHASAR)
        self.assertEqual(output.content, "別の思考内容")


class TestDebateOutput(unittest.TestCase):
    """DebateOutputデータクラスのテスト"""

    def test_debate_output_creation(self):
        """DebateOutputが正しく作成されること"""
        from magi.models import DebateOutput, PersonaType
        timestamp = datetime.now()
        responses = {
            PersonaType.MELCHIOR: "メルキオールへの反論",
            PersonaType.BALTHASAR: "バルタザールへの反論"
        }
        output = DebateOutput(
            persona_type=PersonaType.CASPER,
            round_number=1,
            responses=responses,
            timestamp=timestamp
        )
        self.assertEqual(output.persona_type, PersonaType.CASPER)
        self.assertEqual(output.round_number, 1)
        self.assertEqual(output.responses, responses)
        self.assertEqual(output.timestamp, timestamp)

    def test_debate_output_with_empty_responses(self):
        """空のresponsesでDebateOutputが作成できること"""
        from magi.models import DebateOutput, PersonaType
        timestamp = datetime.now()
        output = DebateOutput(
            persona_type=PersonaType.MELCHIOR,
            round_number=2,
            responses={},
            timestamp=timestamp
        )
        self.assertEqual(output.round_number, 2)
        self.assertEqual(output.responses, {})


class TestVoteOutput(unittest.TestCase):
    """VoteOutputデータクラスのテスト"""

    def test_vote_output_creation(self):
        """VoteOutputが正しく作成されること"""
        from magi.models import VoteOutput, PersonaType, Vote
        output = VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="承認理由",
            conditions=None
        )
        self.assertEqual(output.persona_type, PersonaType.MELCHIOR)
        self.assertEqual(output.vote, Vote.APPROVE)
        self.assertEqual(output.reason, "承認理由")
        self.assertIsNone(output.conditions)

    def test_vote_output_with_conditions(self):
        """条件付きでVoteOutputが作成できること"""
        from magi.models import VoteOutput, PersonaType, Vote
        conditions = ["条件1", "条件2"]
        output = VoteOutput(
            persona_type=PersonaType.BALTHASAR,
            vote=Vote.CONDITIONAL,
            reason="条件付き承認",
            conditions=conditions
        )
        self.assertEqual(output.vote, Vote.CONDITIONAL)
        self.assertEqual(output.conditions, conditions)

    def test_vote_output_without_conditions(self):
        """conditionsがデフォルトでNoneになること"""
        from magi.models import VoteOutput, PersonaType, Vote
        output = VoteOutput(
            persona_type=PersonaType.CASPER,
            vote=Vote.DENY,
            reason="否認理由"
        )
        self.assertIsNone(output.conditions)


class TestDebateRound(unittest.TestCase):
    """DebateRoundデータクラスのテスト"""

    def test_debate_round_creation(self):
        """DebateRoundが正しく作成されること"""
        from magi.models import DebateRound, DebateOutput, PersonaType
        timestamp = datetime.now()
        outputs = {
            PersonaType.MELCHIOR: DebateOutput(
                persona_type=PersonaType.MELCHIOR,
                round_number=1,
                responses={},
                timestamp=timestamp
            ),
            PersonaType.BALTHASAR: DebateOutput(
                persona_type=PersonaType.BALTHASAR,
                round_number=1,
                responses={},
                timestamp=timestamp
            )
        }
        round_obj = DebateRound(
            round_number=1,
            outputs=outputs,
            timestamp=timestamp
        )
        self.assertEqual(round_obj.round_number, 1)
        self.assertEqual(round_obj.outputs, outputs)
        self.assertEqual(round_obj.timestamp, timestamp)

    def test_debate_round_with_empty_outputs(self):
        """空のoutputsでDebateRoundが作成できること"""
        from magi.models import DebateRound
        timestamp = datetime.now()
        round_obj = DebateRound(
            round_number=2,
            outputs={},
            timestamp=timestamp
        )
        self.assertEqual(round_obj.round_number, 2)
        self.assertEqual(round_obj.outputs, {})


class TestConsensusResult(unittest.TestCase):
    """ConsensusResultデータクラスのテスト"""

    def test_consensus_result_creation(self):
        """ConsensusResultが正しく作成されること"""
        from magi.models import (
            ConsensusResult, ThinkingOutput, DebateRound,
            PersonaType, Vote, Decision
        )
        timestamp = datetime.now()
        thinking_results = {
            "melchior": ThinkingOutput(
                persona_type=PersonaType.MELCHIOR,
                content="思考内容",
                timestamp=timestamp
            )
        }
        debate_results = [
            DebateRound(
                round_number=1,
                outputs={},
                timestamp=timestamp
            )
        ]
        voting_results = {
            "melchior": Vote.APPROVE
        }
        result = ConsensusResult(
            thinking_results=thinking_results,
            debate_results=debate_results,
            voting_results=voting_results,
            final_decision=Decision.APPROVED,
            exit_code=0
        )
        self.assertEqual(result.thinking_results, thinking_results)
        self.assertEqual(result.debate_results, debate_results)
        self.assertEqual(result.voting_results, voting_results)
        self.assertEqual(result.final_decision, Decision.APPROVED)
        self.assertEqual(result.exit_code, 0)

    def test_consensus_result_with_denied_decision(self):
        """DENIED判定でConsensusResultが作成できること"""
        from magi.models import (
            ConsensusResult, ThinkingOutput, DebateRound,
            PersonaType, Vote, Decision
        )
        timestamp = datetime.now()
        result = ConsensusResult(
            thinking_results={},
            debate_results=[],
            voting_results={},
            final_decision=Decision.DENIED,
            exit_code=1
        )
        self.assertEqual(result.final_decision, Decision.DENIED)
        self.assertEqual(result.exit_code, 1)

    def test_consensus_result_with_conditional_decision(self):
        """CONDITIONAL判定でConsensusResultが作成できること"""
        from magi.models import (
            ConsensusResult, ThinkingOutput, DebateRound,
            PersonaType, Vote, Decision
        )
        timestamp = datetime.now()
        result = ConsensusResult(
            thinking_results={},
            debate_results=[],
            voting_results={},
            final_decision=Decision.CONDITIONAL,
            exit_code=2
        )
        self.assertEqual(result.final_decision, Decision.CONDITIONAL)
        self.assertEqual(result.exit_code, 2)


if __name__ == "__main__":
    unittest.main()
