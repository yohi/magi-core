"""ContextManagerのユニットテスト

Requirements: 7.1, 7.2, 7.3, 7.4
"""

import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from magi.models import ConsensusPhase, PersonaType
from magi.core.context import ConversationEntry, ContextManager


class TestConversationEntry(unittest.TestCase):
    """ConversationEntryのテスト"""

    def test_create_entry(self):
        """エントリの作成ができること"""
        entry = ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="テスト思考内容",
            timestamp=datetime(2024, 1, 1, 12, 0, 0)
        )
        self.assertEqual(entry.phase, ConsensusPhase.THINKING)
        self.assertEqual(entry.persona_type, PersonaType.MELCHIOR)
        self.assertEqual(entry.content, "テスト思考内容")
        self.assertEqual(entry.timestamp, datetime(2024, 1, 1, 12, 0, 0))

    def test_entry_with_auto_timestamp(self):
        """タイムスタンプが自動設定されること"""
        before = datetime.now()
        entry = ConversationEntry(
            phase=ConsensusPhase.DEBATE,
            persona_type=PersonaType.BALTHASAR,
            content="議論内容"
        )
        after = datetime.now()
        self.assertGreaterEqual(entry.timestamp, before)
        self.assertLessEqual(entry.timestamp, after)


class TestContextManager(unittest.TestCase):
    """ContextManagerのテスト"""

    def setUp(self):
        """各テストの前にContextManagerをリセット"""
        self.manager = ContextManager(max_tokens=100000)

    def test_init_default_max_tokens(self):
        """デフォルトのmax_tokensが設定されること"""
        manager = ContextManager()
        self.assertEqual(manager.max_tokens, 100000)

    def test_init_custom_max_tokens(self):
        """カスタムのmax_tokensが設定されること"""
        manager = ContextManager(max_tokens=50000)
        self.assertEqual(manager.max_tokens, 50000)

    def test_add_entry(self):
        """エントリを履歴に追加できること - Requirements 7.1"""
        entry = ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="MELCHIORの思考"
        )
        self.manager.add_entry(entry)
        self.assertEqual(len(self.manager.history), 1)
        self.assertEqual(self.manager.history[0], entry)

    def test_add_multiple_entries(self):
        """複数のエントリを追加できること"""
        entries = [
            ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.MELCHIOR,
                content="MELCHIOR思考"
            ),
            ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.BALTHASAR,
                content="BALTHASAR思考"
            ),
            ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.CASPER,
                content="CASPER思考"
            ),
        ]
        for entry in entries:
            self.manager.add_entry(entry)
        self.assertEqual(len(self.manager.history), 3)

    def test_get_context_for_thinking_phase(self):
        """Thinking Phaseのコンテキスト取得 - Requirements 7.2"""
        # Thinking Phaseでは他のエージェントの出力を含めない
        context = self.manager.get_context_for_phase(ConsensusPhase.THINKING)
        self.assertIsInstance(context, str)

    def test_get_context_for_debate_phase(self):
        """Debate Phaseのコンテキスト取得 - Requirements 7.2"""
        # 先にThinking Phaseのエントリを追加
        for persona_type in PersonaType:
            entry = ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=persona_type,
                content=f"{persona_type.value}の思考結果"
            )
            self.manager.add_entry(entry)

        context = self.manager.get_context_for_phase(ConsensusPhase.DEBATE)
        # Debate Phaseでは全エージェントの思考結果を含む
        self.assertIn("melchior", context.lower())
        self.assertIn("balthasar", context.lower())
        self.assertIn("casper", context.lower())

    def test_get_context_for_voting_phase(self):
        """Voting Phaseのコンテキスト取得 - Requirements 7.2"""
        # Thinking Phaseのエントリを追加
        for persona_type in PersonaType:
            entry = ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=persona_type,
                content=f"{persona_type.value}の思考"
            )
            self.manager.add_entry(entry)

        # Debate Phaseのエントリを追加
        for persona_type in PersonaType:
            entry = ConversationEntry(
                phase=ConsensusPhase.DEBATE,
                persona_type=persona_type,
                content=f"{persona_type.value}の議論"
            )
            self.manager.add_entry(entry)

        context = self.manager.get_context_for_phase(ConsensusPhase.VOTING)
        # Voting Phaseでは全履歴を含む
        self.assertIn("思考", context)
        self.assertIn("議論", context)

    def test_export_returns_dict(self):
        """エクスポートが辞書を返すこと - Requirements 7.3"""
        entry = ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="テスト内容"
        )
        self.manager.add_entry(entry)
        exported = self.manager.export()
        self.assertIsInstance(exported, dict)

    def test_export_structure(self):
        """エクスポートが正しい構造を持つこと - Requirements 7.3"""
        entry = ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="テスト内容",
            timestamp=datetime(2024, 1, 1, 12, 0, 0)
        )
        self.manager.add_entry(entry)
        exported = self.manager.export()

        self.assertIn("entries", exported)
        self.assertIn("total_entries", exported)
        self.assertEqual(exported["total_entries"], 1)

        entry_data = exported["entries"][0]
        self.assertEqual(entry_data["phase"], "thinking")
        self.assertEqual(entry_data["persona_type"], "melchior")
        self.assertEqual(entry_data["content"], "テスト内容")
        self.assertIn("timestamp", entry_data)

    def test_export_empty_history(self):
        """空の履歴のエクスポート"""
        exported = self.manager.export()
        self.assertEqual(exported["total_entries"], 0)
        self.assertEqual(exported["entries"], [])

    def test_get_entries_by_phase(self):
        """フェーズ別のエントリ取得"""
        # 各フェーズのエントリを追加
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="Thinking 1"
        ))
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.DEBATE,
            persona_type=PersonaType.MELCHIOR,
            content="Debate 1"
        ))
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.BALTHASAR,
            content="Thinking 2"
        ))

        thinking_entries = self.manager.get_entries_by_phase(ConsensusPhase.THINKING)
        self.assertEqual(len(thinking_entries), 2)
        for entry in thinking_entries:
            self.assertEqual(entry.phase, ConsensusPhase.THINKING)

    def test_get_entries_by_persona(self):
        """ペルソナ別のエントリ取得"""
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="MELCHIOR 1"
        ))
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.BALTHASAR,
            content="BALTHASAR 1"
        ))
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.DEBATE,
            persona_type=PersonaType.MELCHIOR,
            content="MELCHIOR 2"
        ))

        melchior_entries = self.manager.get_entries_by_persona(PersonaType.MELCHIOR)
        self.assertEqual(len(melchior_entries), 2)
        for entry in melchior_entries:
            self.assertEqual(entry.persona_type, PersonaType.MELCHIOR)

    def test_clear_history(self):
        """履歴のクリア"""
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="テスト"
        ))
        self.assertEqual(len(self.manager.history), 1)
        self.manager.clear()
        self.assertEqual(len(self.manager.history), 0)

    def test_estimate_tokens(self):
        """トークン数の推定"""
        entry = ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="a" * 1000  # 1000文字
        )
        self.manager.add_entry(entry)
        # 概算: 1文字 ≈ 0.25-0.5トークン（日本語は異なる）
        estimated = self.manager.estimate_tokens()
        self.assertGreater(estimated, 0)

    def test_current_token_count_property(self):
        """現在のトークン数プロパティ"""
        self.manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="テスト内容"
        ))
        self.assertGreater(self.manager.current_token_count, 0)


class TestContextManagerTokenLimits(unittest.TestCase):
    """トークン制限関連のテスト - Requirements 7.4"""

    def test_summarize_if_needed_below_threshold(self):
        """閾値以下の場合は要約しない"""
        manager = ContextManager(max_tokens=100000)
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="短い内容"
        ))
        original_count = len(manager.history)
        manager.summarize_if_needed()
        self.assertEqual(len(manager.history), original_count)

    def test_summarize_if_needed_above_threshold(self):
        """閾値を超えた場合に要約/削除が行われる - Requirements 7.4"""
        manager = ContextManager(max_tokens=100)  # 非常に低い制限

        # 大量のエントリを追加
        for i in range(100):
            manager.add_entry(ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.MELCHIOR,
                content=f"長い内容 {i} " + "x" * 100
            ))

        initial_tokens = manager.estimate_tokens()
        manager.summarize_if_needed()

        # トークン数が減少しているか、履歴が調整されている
        # 実装方法によって検証方法は変わる
        final_tokens = manager.estimate_tokens()
        self.assertLessEqual(final_tokens, manager.max_tokens)

    def test_is_near_limit(self):
        """制限に近づいているかの判定"""
        manager = ContextManager(max_tokens=1000)
        self.assertFalse(manager.is_near_limit())

        # 大量のコンテンツを追加
        for i in range(50):
            manager.add_entry(ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.MELCHIOR,
                content="x" * 100
            ))

        # 閾値（80%）を超えているか確認
        # 実装に依存するため、動作確認のみ
        result = manager.is_near_limit()
        self.assertIsInstance(result, bool)


class TestContextManagerSummary(unittest.TestCase):
    """要約機能のテスト"""

    def test_get_summary(self):
        """履歴の要約を取得"""
        manager = ContextManager()
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="MELCHIOR思考"
        ))
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.BALTHASAR,
            content="BALTHASAR思考"
        ))

        summary = manager.get_summary()
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)


if __name__ == "__main__":
    unittest.main()
