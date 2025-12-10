"""TokenBudgetManager のプロパティテスト"""

import unittest

from hypothesis import given, settings, strategies as st

from magi.core.token_budget import TokenBudgetManager
from magi.models import ConsensusPhase


class TestTokenBudgetProperties(unittest.TestCase):
    """トークン予算強制の性質を検証する"""

    @given(st.text(min_size=1, max_size=16000))
    @settings(max_examples=50, deadline=None)
    def test_enforce_never_exceeds_budget(self, context: str):
        """どの入力でも予算を超えない"""
        manager = TokenBudgetManager(max_tokens=256, tokens_per_char=0.5)
        result = manager.enforce(context, ConsensusPhase.VOTING)

        self.assertLessEqual(
            manager.estimate_tokens(result.context), manager.max_tokens
        )
        if len(context) <= int(manager.max_tokens / manager.tokens_per_char):
            self.assertFalse(result.summary_applied)
            self.assertEqual([], result.logs)
        else:
            self.assertTrue(result.summary_applied)
            self.assertGreaterEqual(len(result.logs), 1)
            for log in result.logs:
                self.assertGreater(log.before_tokens, 0)
                self.assertGreaterEqual(log.after_tokens, 0)
                self.assertGreaterEqual(log.retain_ratio, 0.0)
                self.assertLessEqual(log.retain_ratio, 1.0)
                self.assertIn(
                    log.strategy,
                    ("priority_only", "with_summary", "trim_to_budget"),
                )
                self.assertIsInstance(log.summary_applied, bool)


if __name__ == "__main__":  # pragma: no cover - 実行用
    unittest.main()

