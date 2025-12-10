"""ペルソナ管理のプロパティベーステスト

Property 3: オーバーライド適用の保全性
- Validates: Requirements 3.5, 8.4
"""
import unittest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from magi.models import PersonaType
from magi.agents.persona import Persona, PersonaManager


# ペルソナ名の戦略（有効な名前）
persona_names = st.sampled_from(["melchior", "balthasar", "casper"])

# ペルソナ名の戦略（大文字小文字のバリエーションを含む）
persona_names_with_case = st.sampled_from([
    "melchior", "MELCHIOR", "Melchior",
    "balthasar", "BALTHASAR", "Balthasar",
    "casper", "CASPER", "Casper"
])

# オーバーライドプロンプトの戦略
override_prompt_strategy = st.text(min_size=0, max_size=1000)

# オーバーライド辞書の戦略（0〜3個のペルソナに対するオーバーライド）
overrides_strategy = st.dictionaries(
    keys=persona_names,
    values=st.text(min_size=1, max_size=500),
    min_size=0,
    max_size=3
)


# **Feature: magi-core, Property 3: オーバーライド適用の保全性**
# **Validates: Requirements 3.5, 8.4**
class TestOverridePreservation(unittest.TestCase):
    """オーバーライド適用の保全性プロパティテスト

    Property 3: For any プラグインのagent_overridesに対して、
    適用後のシステムプロンプトは基本プロンプトとオーバーライドの両方を含む
    """

    @given(override_prompt=override_prompt_strategy)
    @settings(max_examples=100)
    def test_override_preserves_base_prompt(self, override_prompt: str):
        """オーバーライド適用後も基本プロンプトが保持される

        任意のオーバーライドプロンプトに対して、
        基本プロンプトが変更されないことを検証する。
        """
        manager = PersonaManager()

        # 各ペルソナに対してテスト
        for persona_type in PersonaType:
            original_base = manager.get_persona(persona_type).base_prompt

            # オーバーライドを適用
            overrides = {persona_type.value: override_prompt}
            manager.apply_overrides(overrides)

            persona = manager.get_persona(persona_type)

            # 基本プロンプトが保持されていることを確認
            self.assertEqual(persona.base_prompt, original_base)

            # オーバーライドをクリア（次のイテレーションのため）
            manager.clear_overrides()

    @given(overrides=overrides_strategy)
    @settings(max_examples=100)
    def test_system_prompt_contains_both(self, overrides: dict):
        """システムプロンプトは基本プロンプトとオーバーライドの両方を含む

        任意のオーバーライド辞書に対して、
        system_promptが基本プロンプトとオーバーライドの両方を含むことを検証する。
        """
        manager = PersonaManager()

        # 元の基本プロンプトを保存
        original_bases = {
            pt: manager.get_persona(pt).base_prompt
            for pt in PersonaType
        }

        # オーバーライドを適用
        manager.apply_overrides(overrides)

        # 各ペルソナを検証
        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            persona_name = persona_type.value

            # 基本プロンプトが含まれることを確認
            self.assertIn(original_bases[persona_type], persona.system_prompt)

            # オーバーライドがある場合、それも含まれることを確認
            if persona_name in overrides and overrides[persona_name]:
                self.assertIn(overrides[persona_name], persona.system_prompt)

    @given(overrides=overrides_strategy)
    @settings(max_examples=100)
    def test_override_does_not_affect_other_personas(self, overrides: dict):
        """オーバーライドは他のペルソナに影響しない

        あるペルソナへのオーバーライドが他のペルソナに影響しないことを検証する。
        """
        manager = PersonaManager()

        # オーバーライドを適用
        manager.apply_overrides(overrides)

        # 各ペルソナを検証
        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            persona_name = persona_type.value

            if persona_name in overrides:
                # オーバーライドがある場合
                self.assertEqual(persona.override_prompt, overrides[persona_name])
            else:
                # オーバーライドがない場合
                self.assertIsNone(persona.override_prompt)

    @given(override_prompt=st.text(min_size=1, max_size=500))
    @settings(max_examples=100)
    def test_multiple_override_applications(self, override_prompt: str):
        """複数回のオーバーライド適用でも基本プロンプトが保持される

        オーバーライドを複数回適用しても、
        基本プロンプトが変更されないことを検証する。
        """
        manager = PersonaManager()

        # 元の基本プロンプトを保存
        original_bases = {
            pt: manager.get_persona(pt).base_prompt
            for pt in PersonaType
        }

        # 複数回オーバーライドを適用
        for i in range(5):
            overrides = {pt.value: f"{override_prompt}_{i}" for pt in PersonaType}
            manager.apply_overrides(overrides)

            # 各ペルソナの基本プロンプトが保持されていることを確認
            for persona_type in PersonaType:
                persona = manager.get_persona(persona_type)
                self.assertEqual(persona.base_prompt, original_bases[persona_type])


class TestPersonaSystemPromptProperty(unittest.TestCase):
    """Personaのsystem_promptプロパティのテスト"""

    @given(
        base_prompt=st.text(min_size=1, max_size=500),
        override_prompt=st.text(min_size=0, max_size=500)
    )
    @settings(max_examples=100)
    def test_system_prompt_structure(self, base_prompt: str, override_prompt: str):
        """system_promptは正しい構造を持つ

        基本プロンプトとオーバーライドの結合形式を検証する。
        """
        assume(len(base_prompt.strip()) > 0)  # 空白のみの基本プロンプトは除外

        persona = Persona(
            type=PersonaType.MELCHIOR,
            name="MELCHIOR-1",
            base_prompt=base_prompt,
            override_prompt=override_prompt if override_prompt else None
        )

        if override_prompt:
            # オーバーライドがある場合
            expected = f"{base_prompt}\n\n{override_prompt}"
            self.assertEqual(persona.system_prompt, expected)
        else:
            # オーバーライドがない場合
            self.assertEqual(persona.system_prompt, base_prompt)

    @given(base_prompt=st.text(min_size=1, max_size=500))
    @settings(max_examples=100)
    def test_system_prompt_without_override_equals_base(self, base_prompt: str):
        """オーバーライドがない場合、system_promptはbase_promptと等しい"""
        assume(len(base_prompt.strip()) > 0)

        persona = Persona(
            type=PersonaType.BALTHASAR,
            name="BALTHASAR-2",
            base_prompt=base_prompt
        )

        self.assertEqual(persona.system_prompt, base_prompt)


class TestClearOverridesProperty(unittest.TestCase):
    """clear_overridesのプロパティテスト"""

    @given(overrides=overrides_strategy)
    @settings(max_examples=100)
    def test_clear_removes_all_overrides(self, overrides: dict):
        """clear_overridesは全てのオーバーライドを削除する"""
        manager = PersonaManager()

        # オーバーライドを適用
        manager.apply_overrides(overrides)

        # クリア
        manager.clear_overrides()

        # 全てのオーバーライドがNoneであることを確認
        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            self.assertIsNone(persona.override_prompt)

    @given(overrides=overrides_strategy)
    @settings(max_examples=100)
    def test_clear_preserves_base_prompts(self, overrides: dict):
        """clear_overridesは基本プロンプトを保持する"""
        manager = PersonaManager()

        # 元の基本プロンプトを保存
        original_bases = {
            pt: manager.get_persona(pt).base_prompt
            for pt in PersonaType
        }

        # オーバーライド → クリア
        manager.apply_overrides(overrides)
        manager.clear_overrides()

        # 基本プロンプトが保持されていることを確認
        for persona_type in PersonaType:
            persona = manager.get_persona(persona_type)
            self.assertEqual(persona.base_prompt, original_bases[persona_type])


if __name__ == '__main__':
    unittest.main()

