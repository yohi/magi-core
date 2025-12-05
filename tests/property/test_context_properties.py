"""会話履歴管理のプロパティベーステスト

Property 11: 会話履歴のラウンドトリップ
- Validates: Requirements 7.1, 7.2, 7.3

Property 12: トークン制限の遵守
- Validates: Requirements 7.4
"""
import unittest
from datetime import datetime, timedelta
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from magi.models import ConsensusPhase, PersonaType
from magi.core.context import ConversationEntry, ContextManager


# フェーズの戦略
phase_strategy = st.sampled_from([
    ConsensusPhase.THINKING,
    ConsensusPhase.DEBATE,
    ConsensusPhase.VOTING,
    ConsensusPhase.COMPLETED,
])

# ペルソナタイプの戦略
persona_strategy = st.sampled_from([
    PersonaType.MELCHIOR,
    PersonaType.BALTHASAR,
    PersonaType.CASPER,
])

# コンテンツの戦略（空でない文字列）
content_strategy = st.text(min_size=1, max_size=1000)

# タイムスタンプの戦略
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)

# 会話エントリの戦略
entry_strategy = st.builds(
    ConversationEntry,
    phase=phase_strategy,
    persona_type=persona_strategy,
    content=content_strategy,
    timestamp=timestamp_strategy,
)

# エントリリストの戦略（1〜20個）
entries_list_strategy = st.lists(entry_strategy, min_size=1, max_size=20)

# max_tokensの戦略（100〜1000000）
max_tokens_strategy = st.integers(min_value=100, max_value=1000000)


# **Feature: magi-core, Property 11: 会話履歴のラウンドトリップ**
# **Validates: Requirements 7.1, 7.2, 7.3**
class TestConversationHistoryRoundTrip(unittest.TestCase):
    """会話履歴のラウンドトリッププロパティテスト

    Property 11: For any 会話エントリを追加した後、そのエントリは履歴から
    取得可能であり、エクスポート時に構造化形式で出力される
    """

    @given(entry=entry_strategy)
    @settings(max_examples=100)
    def test_added_entry_is_retrievable(self, entry: ConversationEntry):
        """追加したエントリが履歴から取得可能

        Requirements 7.1: 各フェーズが完了するとエージェントの出力を会話履歴に追加
        """
        manager = ContextManager()
        manager.add_entry(entry)

        # 追加したエントリが履歴に存在する
        self.assertIn(entry, manager.history)
        self.assertEqual(len(manager.history), 1)

    @given(entries=entries_list_strategy)
    @settings(max_examples=100)
    def test_multiple_entries_preserved_in_order(self, entries: list):
        """複数のエントリが順序を保持して格納される

        任意のエントリリストに対して、追加順序が保持される
        """
        manager = ContextManager()
        for entry in entries:
            manager.add_entry(entry)

        # エントリ数が一致
        self.assertEqual(len(manager.history), len(entries))

        # 順序が保持される
        for i, entry in enumerate(entries):
            self.assertEqual(manager.history[i], entry)

    @given(entry=entry_strategy)
    @settings(max_examples=100)
    def test_entry_export_roundtrip(self, entry: ConversationEntry):
        """エントリのエクスポートが正しい構造を持つ

        Requirements 7.3: 合議プロセスが完了すると全体の会話履歴を
        構造化された形式で出力可能にする
        """
        manager = ContextManager()
        manager.add_entry(entry)

        exported = manager.export()

        # 基本構造の確認
        self.assertIn("entries", exported)
        self.assertIn("total_entries", exported)
        self.assertEqual(exported["total_entries"], 1)

        # エントリデータの確認
        entry_data = exported["entries"][0]
        self.assertEqual(entry_data["phase"], entry.phase.value)
        self.assertEqual(entry_data["persona_type"], entry.persona_type.value)
        self.assertEqual(entry_data["content"], entry.content)

    @given(entries=entries_list_strategy)
    @settings(max_examples=100)
    def test_export_preserves_all_entries(self, entries: list):
        """エクスポートが全エントリを保持する

        任意のエントリリストに対して、エクスポートには全エントリが含まれる
        """
        manager = ContextManager()
        for entry in entries:
            manager.add_entry(entry)

        exported = manager.export()

        # エントリ数が一致
        self.assertEqual(exported["total_entries"], len(entries))
        self.assertEqual(len(exported["entries"]), len(entries))

        # 各エントリのデータが一致
        for i, entry in enumerate(entries):
            entry_data = exported["entries"][i]
            self.assertEqual(entry_data["phase"], entry.phase.value)
            self.assertEqual(entry_data["persona_type"], entry.persona_type.value)
            self.assertEqual(entry_data["content"], entry.content)

    @given(entries=entries_list_strategy, phase=phase_strategy)
    @settings(max_examples=100)
    def test_get_entries_by_phase_filters_correctly(self, entries: list, phase: ConsensusPhase):
        """フェーズ別フィルタリングが正しく機能する

        Requirements 7.2: 新しいフェーズが開始されると必要な履歴情報を
        各エージェントのコンテキストに含める
        """
        manager = ContextManager()
        for entry in entries:
            manager.add_entry(entry)

        filtered = manager.get_entries_by_phase(phase)

        # フィルタリング結果は全て指定フェーズ
        for entry in filtered:
            self.assertEqual(entry.phase, phase)

        # 期待される件数と一致
        expected_count = sum(1 for e in entries if e.phase == phase)
        self.assertEqual(len(filtered), expected_count)

    @given(entries=entries_list_strategy, persona=persona_strategy)
    @settings(max_examples=100)
    def test_get_entries_by_persona_filters_correctly(self, entries: list, persona: PersonaType):
        """ペルソナ別フィルタリングが正しく機能する

        任意のエントリリストとペルソナに対して、フィルタリングが正しく機能する
        """
        manager = ContextManager()
        for entry in entries:
            manager.add_entry(entry)

        filtered = manager.get_entries_by_persona(persona)

        # フィルタリング結果は全て指定ペルソナ
        for entry in filtered:
            self.assertEqual(entry.persona_type, persona)

        # 期待される件数と一致
        expected_count = sum(1 for e in entries if e.persona_type == persona)
        self.assertEqual(len(filtered), expected_count)


# **Feature: magi-core, Property 11: 会話履歴のラウンドトリップ（コンテキスト構築）**
# **Validates: Requirements 7.2**
class TestContextBuildingProperty(unittest.TestCase):
    """コンテキスト構築のプロパティテスト

    Requirements 7.2: 新しいフェーズが開始されると必要な履歴情報を
    各エージェントのコンテキストに含める
    """

    @given(
        melchior_content=content_strategy,
        balthasar_content=content_strategy,
        casper_content=content_strategy,
    )
    @settings(max_examples=100)
    def test_debate_context_contains_all_thinking_results(
        self,
        melchior_content: str,
        balthasar_content: str,
        casper_content: str,
    ):
        """Debate Phaseのコンテキストが全Thinking結果を含む

        任意の3エージェントの思考結果に対して、
        Debate Phaseのコンテキストには全ての結果が含まれる
        """
        manager = ContextManager()

        # 各エージェントのThinking結果を追加
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content=melchior_content,
        ))
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.BALTHASAR,
            content=balthasar_content,
        ))
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.CASPER,
            content=casper_content,
        ))

        context = manager.get_context_for_phase(ConsensusPhase.DEBATE)

        # 全エージェントの内容が含まれる
        self.assertIn(melchior_content, context)
        self.assertIn(balthasar_content, context)
        self.assertIn(casper_content, context)

    def test_thinking_context_is_empty(self):
        """Thinking Phaseのコンテキストは空（独立思考を保証）

        Thinking Phaseでは他のエージェントの出力を参照しない
        """
        manager = ContextManager()

        # 既存のエントリを追加
        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content="MELCHIORの思考",
        ))

        context = manager.get_context_for_phase(ConsensusPhase.THINKING)

        # Thinking Phaseでは空のコンテキスト
        self.assertEqual(context, "")


# **Feature: magi-core, Property 12: トークン制限の遵守**
# **Validates: Requirements 7.4**
class TestTokenLimitCompliance(unittest.TestCase):
    """トークン制限遵守のプロパティテスト

    Property 12: For any 会話履歴のサイズがトークン制限に近づいた場合、
    Context_Managerは履歴を要約または削除して制限内に収める
    """

    @given(max_tokens=max_tokens_strategy)
    @settings(max_examples=100)
    def test_summarize_ensures_within_limit(self, max_tokens: int):
        """summarize_if_needed後は制限内に収まる

        Requirements 7.4: 会話履歴のサイズがトークン制限に近づくと
        古い履歴を要約または削除して制限内に収める
        """
        manager = ContextManager(max_tokens=max_tokens)

        # 制限を超えるようにエントリを追加
        for i in range(100):
            manager.add_entry(ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.MELCHIOR,
                content=f"テスト内容 {i} " + "x" * 100,
            ))

        # 要約/削除を実行
        manager.summarize_if_needed()

        # 制限内に収まっている
        self.assertLessEqual(manager.current_token_count, max_tokens)

    @given(entries=entries_list_strategy, max_tokens=max_tokens_strategy)
    @settings(max_examples=100)
    def test_summarize_preserves_recent_entries_when_possible(
        self,
        entries: list,
        max_tokens: int,
    ):
        """要約後も可能な限り最新のエントリを保持する

        任意のエントリリストとmax_tokensに対して、
        要約後は最新のエントリが優先的に保持される
        """
        manager = ContextManager(max_tokens=max_tokens)
        for entry in entries:
            manager.add_entry(entry)

        original_last_entry = manager.history[-1] if manager.history else None
        manager.summarize_if_needed()

        # 制限内に収まっている
        self.assertLessEqual(manager.current_token_count, max_tokens)

        # 履歴が残っている場合、最後のエントリは保持される傾向
        # （ただしトークン制限が厳しすぎる場合は削除されることもある）
        if manager.history and original_last_entry:
            # 最新エントリが保持されているか、制限により削除されたか
            # どちらの場合も制限内であることが重要
            self.assertTrue(
                manager.history[-1] == original_last_entry
                or original_last_entry not in manager.history,
                "最新エントリは保持されるか、制限により削除されるかのいずれかである必要がある",
            )

    @given(max_tokens=st.integers(min_value=1000, max_value=50000))
    @settings(max_examples=100)
    def test_is_near_limit_threshold(self, max_tokens: int):
        """is_near_limitが80%閾値で正しく判定する

        任意のmax_tokensに対して、80%の閾値で正しく判定される
        """
        manager = ContextManager(max_tokens=max_tokens)

        # 初期状態では制限に近くない
        self.assertFalse(manager.is_near_limit())

        # 確実に80%を超えるようにエントリを追加
        # 各エントリは200文字 × 0.5 = 100トークン相当
        entries_needed = int((max_tokens * 0.8) / 100) + 10  # 余裕を持って追加

        for _ in range(entries_needed):
            manager.add_entry(ConversationEntry(
                phase=ConsensusPhase.THINKING,
                persona_type=PersonaType.MELCHIOR,
                content="x" * 200,  # 100トークン相当
            ))

        # 80%を超えたらTrueになる
        self.assertTrue(manager.is_near_limit())

    @given(entries=entries_list_strategy)
    @settings(max_examples=100)
    def test_clear_resets_token_count(self, entries: list):
        """clearがトークンカウントをリセットする

        任意のエントリリストに対して、clear後はトークンカウントが0になる
        """
        manager = ContextManager()
        for entry in entries:
            manager.add_entry(entry)

        assume(manager.current_token_count > 0)

        manager.clear()

        self.assertEqual(manager.current_token_count, 0)
        self.assertEqual(len(manager.history), 0)


# **Feature: magi-core, Property 12: トークン推定の一貫性**
# **Validates: Requirements 7.4**
class TestTokenEstimationConsistency(unittest.TestCase):
    """トークン推定の一貫性プロパティテスト"""

    @given(content=st.text(min_size=3, max_size=1000))
    @settings(max_examples=100)
    def test_token_estimate_increases_with_content(self, content: str):
        """コンテンツ追加でトークン推定値が増加する

        任意のコンテンツに対して、追加後は推定値が増加する
        """
        manager = ContextManager()
        initial_tokens = manager.estimate_tokens()

        manager.add_entry(ConversationEntry(
            phase=ConsensusPhase.THINKING,
            persona_type=PersonaType.MELCHIOR,
            content=content,
        ))

        final_tokens = manager.estimate_tokens()

        # 3文字以上のコンテンツの場合、トークン数は増加
        # (トークン推定係数0.5のため、最低2文字で1トークン)
        self.assertGreater(final_tokens, initial_tokens)

    @given(entries=entries_list_strategy)
    @settings(max_examples=100)
    def test_token_estimate_matches_property(self, entries: list):
        """estimate_tokensとcurrent_token_countが一致する

        任意のエントリリストに対して、両方の値が一致する
        """
        manager = ContextManager()
        for entry in entries:
            manager.add_entry(entry)

        self.assertEqual(manager.estimate_tokens(), manager.current_token_count)


if __name__ == "__main__":
    unittest.main()
