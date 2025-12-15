"""TokenBudgetManagerのユニットテスト."""

import unittest

from magi.core.token_budget import (
    SimpleTokenBudgetManager,
    TokenBudgetManager,
    TokenBudgetManagerProtocol,
)
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
        self.assertGreater(result.logs[0].before_tokens, result.logs[0].after_tokens)

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
        self.assertEqual("token_budget_exceeded_trimmed", result.logs[0].reason)
        self.assertLessEqual(manager.estimate_tokens(result.context), manager.max_tokens)
        self.assertGreater(result.reduced_tokens, 0)
        self.assertGreater(result.logs[0].before_tokens, result.logs[0].after_tokens)

    def test_reduction_log_contains_retention_metrics(self):
        """削減ログに保持率と戦略が含まれる."""
        manager = TokenBudgetManager(max_tokens=60, tokens_per_char=0.5)
        context = "## Heading\n" + ("詳細" * 200)

        result = manager.enforce(context, ConsensusPhase.VOTING)
        self.assertTrue(result.summary_applied)
        self.assertEqual(1, len(result.logs))

        log = result.logs[0]
        self.assertGreater(log.before_tokens, log.after_tokens)
        self.assertGreater(log.retain_ratio, 0)
        self.assertLessEqual(log.retain_ratio, 1.0)
        self.assertIn(log.strategy, ("priority_only", "with_summary", "trim_to_budget"))
        self.assertIsInstance(log.summary_applied, bool)
        self.assertEqual(result.reduced_tokens, log.before_tokens - log.after_tokens)

    def test_invalid_tokens_per_char_raises_value_error(self):
        """tokens_per_char が0以下なら例外を送出する."""
        with self.assertRaises(ValueError):
            TokenBudgetManager(max_tokens=10, tokens_per_char=0)


class TestSimpleTokenBudgetManager(unittest.TestCase):
    """SimpleTokenBudgetManager の基本動作確認."""

    def test_unlimited_budget_always_allows(self):
        """max_tokens=None なら常に許可し、消費は記録しない."""
        manager = SimpleTokenBudgetManager(max_tokens=None)

        self.assertIsInstance(manager, TokenBudgetManagerProtocol)
        self.assertTrue(manager.check_budget(1_000_000))

        # consume しても無制限のまま
        manager.consume(5_000)
        self.assertTrue(manager.check_budget(1))

    def test_check_budget_blocks_when_exceeds_remaining(self):
        """残予算を超える場合は False を返す."""
        manager = SimpleTokenBudgetManager(max_tokens=100)

        self.assertTrue(manager.check_budget(60))
        manager.consume(60)

        self.assertTrue(manager.check_budget(40))
        self.assertFalse(manager.check_budget(41))

    def test_consume_negative_raises_value_error(self):
        """負の消費は例外."""
        manager = SimpleTokenBudgetManager(max_tokens=50)
        with self.assertRaises(ValueError):
            manager.consume(-1)


if __name__ == "__main__":
    unittest.main()
