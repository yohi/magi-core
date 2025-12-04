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


if __name__ == "__main__":
    unittest.main()
