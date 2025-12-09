"""TokenBudgetManagerのユニットテスト."""

import unittest

from magi.core.token_budget import TokenBudgetManager
from magi.models import ConsensusPhase


class TestTokenBudgetManager(unittest.TestCase):
    """TokenBudgetManagerの動作確認."""

    def test_under_budget_no_reduction(self):
        """予算内ならコンテキストを変更しない."""
        manager = TokenBudgetManager(max_tokens=100, tokens_per_char=0.5)
        context = "短いコンテキスト"

        result = manager.enforce(context, ConsensusPhase.VOTING)

        self.assertFalse(result.summary_applied)
        self.assertEqual(context, result.context)
        self.assertEqual(0, result.reduced_tokens)
        self.assertEqual([], result.logs)

    def test_over_budget_triggers_reduction(self):
        """予算超過時に要約・削減ログを出力する."""
        manager = TokenBudgetManager(max_tokens=50, tokens_per_char=0.5)
        context = "【Thinking Phase結果】\n" + ("詳細" * 80)

        result = manager.enforce(context, ConsensusPhase.VOTING)

        self.assertTrue(result.summary_applied)
        self.assertLessEqual(manager.estimate_tokens(result.context), manager.max_tokens)
        self.assertGreater(result.reduced_tokens, 0)
        self.assertEqual(1, len(result.logs))
        self.assertEqual("voting", result.logs[0].phase)

    def test_heading_priority_is_preserved(self):
        """見出しを含む重要セグメントが優先される."""
        manager = TokenBudgetManager(max_tokens=40, tokens_per_char=0.5)
        context = (
            "【Thinking Phase結果】\n重要A\n\n"
            "ノイズ" * 60 + "\n\n"
            "## まとめ\n結論B"
        )

        result = manager.enforce(context, ConsensusPhase.VOTING)

        self.assertIn("【Thinking", result.context)
        self.assertIn("まとめ", result.context)
        self.assertLessEqual(manager.estimate_tokens(result.context), manager.max_tokens)

    def test_trims_when_no_segment_fits_budget(self):
        """どのセグメントも予算内に収まらない場合は切り詰める."""
        manager = TokenBudgetManager(max_tokens=10, tokens_per_char=1.0)
        context = "非常に長いセグメント" * 5

        result = manager.enforce(context, ConsensusPhase.DEBATE)

        self.assertTrue(result.summary_applied)
        self.assertEqual(1, len(result.logs))
        self.assertEqual("token_budget_exceeded_summary", result.logs[0].reason)
        self.assertLessEqual(manager.estimate_tokens(result.context), manager.max_tokens)
        self.assertGreater(result.reduced_tokens, 0)
        self.assertGreater(result.logs[0].before_tokens, result.logs[0].after_tokens)

    def test_invalid_tokens_per_char_raises_value_error(self):
        """tokens_per_char が0以下なら例外を送出する."""
        with self.assertRaises(ValueError):
            TokenBudgetManager(max_tokens=10, tokens_per_char=0)


if __name__ == "__main__":
    unittest.main()
