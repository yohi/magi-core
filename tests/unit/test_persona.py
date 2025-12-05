"""PersonaManagerのユニットテスト

3賢者のペルソナ管理をテストする。

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""
import unittest
from magi.models import PersonaType


class TestPersona(unittest.TestCase):
    """Personaクラスのテスト"""

    def test_persona_creation(self):
        """ペルソナを正しく作成できる"""
        from magi.agents.persona import Persona

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="論理と科学の視点から分析します。"
        )

        self.assertEqual(persona.type, PersonaType.MELCHIOR)
        self.assertEqual(persona.name, "MELCHIOR-1")
        self.assertEqual(persona.base_prompt, "論理と科学の視点から分析します。")
        self.assertIsNone(persona.override_prompt)

    def test_system_prompt_without_override(self):
        """オーバーライドがない場合、system_promptは基本プロンプトを返す"""
        from magi.agents.persona import Persona

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="基本プロンプト"
        )

        self.assertEqual(persona.system_prompt, "基本プロンプト")

    def test_system_prompt_with_override(self):
        """オーバーライドがある場合、基本プロンプトとオーバーライドを結合する"""
        from magi.agents.persona import Persona

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt="基本プロンプト",
            override_prompt="追加指示"
        )

        expected = "基本プロンプト\n\n追加指示"
        self.assertEqual(persona.system_prompt, expected)


class TestPersonaManager(unittest.TestCase):
    """PersonaManagerクラスのテスト"""

    def test_initialization_creates_all_personas(self):
        """初期化時に3つのペルソナが生成される（Requirements 3.1）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()

        # 全てのペルソナが存在することを確認
        self.assertIn(PersonaType.MELCHIOR, manager.personas)
        self.assertIn(PersonaType.BALTHASAR, manager.personas)
        self.assertIn(PersonaType.CASPER, manager.personas)
        self.assertEqual(len(manager.personas), 3)

    def test_melchior_persona(self):
        """MELCHIOR-1は論理・科学を担当する（Requirements 3.2）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        persona = manager.get_persona(PersonaType.MELCHIOR)

        self.assertEqual(persona.name, "MELCHIOR-1")
        self.assertIn("論理", persona.base_prompt)

    def test_balthasar_persona(self):
        """BALTHASAR-2は倫理・保護を担当する（Requirements 3.3）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        persona = manager.get_persona(PersonaType.BALTHASAR)

        self.assertEqual(persona.name, "BALTHASAR-2")
        self.assertIn("リスク", persona.base_prompt)

    def test_casper_persona(self):
        """CASPER-3は欲望・実利を担当する（Requirements 3.4）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        persona = manager.get_persona(PersonaType.CASPER)

        self.assertEqual(persona.name, "CASPER-3")
        self.assertIn("効率", persona.base_prompt)

    def test_get_persona_returns_correct_persona(self):
        """get_personaは正しいペルソナを返す"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()

        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            self.assertEqual(persona.type, persona_type)

    def test_apply_overrides_to_single_persona(self):
        """apply_overridesは単一のペルソナにオーバーライドを適用できる（Requirements 3.5）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        overrides = {
            "melchior": "コードレビューの視点から分析してください。"
        }

        manager.apply_overrides(overrides)

        melchior = manager.get_persona(PersonaType.MELCHIOR)
        self.assertEqual(melchior.override_prompt, "コードレビューの視点から分析してください。")

        # 他のペルソナに影響がないことを確認
        balthasar = manager.get_persona(PersonaType.BALTHASAR)
        self.assertIsNone(balthasar.override_prompt)

    def test_apply_overrides_to_multiple_personas(self):
        """apply_overridesは複数のペルソナにオーバーライドを適用できる"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        overrides = {
            "melchior": "MELCHIOR用オーバーライド",
            "balthasar": "BALTHASAR用オーバーライド",
            "casper": "CASPER用オーバーライド"
        }

        manager.apply_overrides(overrides)

        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            self.assertIsNotNone(persona.override_prompt)

    def test_apply_overrides_preserves_base_prompt(self):
        """apply_overridesは基本プロンプトを保持する（Property 3）"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        melchior_before = manager.get_persona(PersonaType.MELCHIOR)
        base_prompt_before = melchior_before.base_prompt

        overrides = {
            "melchior": "追加指示"
        }
        manager.apply_overrides(overrides)

        melchior_after = manager.get_persona(PersonaType.MELCHIOR)
        # 基本プロンプトが変更されていないことを確認
        self.assertEqual(melchior_after.base_prompt, base_prompt_before)
        # system_promptは基本プロンプトとオーバーライドを含む
        self.assertIn(base_prompt_before, melchior_after.system_prompt)
        self.assertIn("追加指示", melchior_after.system_prompt)

    def test_apply_overrides_with_empty_dict(self):
        """空の辞書でapply_overridesを呼んでも問題ない"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        manager.apply_overrides({})

        # 全てのペルソナがオーバーライドなしであることを確認
        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            self.assertIsNone(persona.override_prompt)

    def test_apply_overrides_with_unknown_persona(self):
        """未知のペルソナ名は無視される"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        overrides = {
            "unknown_persona": "何か",
            "melchior": "MELCHIOR用オーバーライド"
        }

        # 例外が発生しないことを確認
        manager.apply_overrides(overrides)

        # 既知のペルソナのオーバーライドは適用される
        melchior = manager.get_persona(PersonaType.MELCHIOR)
        self.assertEqual(melchior.override_prompt, "MELCHIOR用オーバーライド")

    def test_clear_overrides(self):
        """clear_overridesで全てのオーバーライドをクリアできる"""
        from magi.agents.persona import PersonaManager

        manager = PersonaManager()
        overrides = {
            "melchior": "オーバーライド",
            "balthasar": "オーバーライド"
        }
        manager.apply_overrides(overrides)

        manager.clear_overrides()

        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            self.assertIsNone(persona.override_prompt)


if __name__ == '__main__':
    unittest.main()
