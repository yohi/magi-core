"""組込みプリセットと解決ロジックのユニットテスト"""

import unittest

from magi.agents.presets import BUILTIN_PRESETS, resolve_preset_prompts


class TestBuiltinPresets(unittest.TestCase):
    """BUILTIN_PRESETS の構造を検証する"""

    def test_arch_preset_exists(self):
        """arch プリセットが3賢者すべてを定義している"""
        self.assertIn("arch", BUILTIN_PRESETS)
        arch = BUILTIN_PRESETS["arch"]
        self.assertIn("melchior", arch)
        self.assertIn("balthasar", arch)
        self.assertIn("casper", arch)

    def test_default_is_not_a_key(self):
        """default はキーとして持たない（base_prompt 据え置きを意味する）"""
        self.assertNotIn("default", BUILTIN_PRESETS)


class TestResolvePresetPrompts(unittest.TestCase):
    """resolve_preset_prompts の解決順序を検証する"""

    def test_none_returns_none(self):
        """--preset 省略時は None（base_prompt 据え置き）"""
        self.assertIsNone(resolve_preset_prompts(None, None))

    def test_default_returns_none(self):
        """default 指定かつ config に default 無しなら None"""
        self.assertIsNone(resolve_preset_prompts("default", {}))

    def test_arch_returns_builtin(self):
        """arch 指定なら組込みの arch プロンプトを返す"""
        result = resolve_preset_prompts("arch", None)
        self.assertEqual(result, BUILTIN_PRESETS["arch"])

    def test_config_overrides_builtin(self):
        """magi.yaml の presets が組込みを上書きする"""
        config_presets = {"arch": {"melchior": "上書き済み"}}
        result = resolve_preset_prompts("arch", config_presets)
        self.assertEqual(result, {"melchior": "上書き済み"})

    def test_config_adds_new_preset(self):
        """magi.yaml で新規プリセットを追加できる"""
        config_presets = {"security": {"melchior": "セキュリティ専門家"}}
        result = resolve_preset_prompts("security", config_presets)
        self.assertEqual(result, {"melchior": "セキュリティ専門家"})

    def test_config_default_overrides_base_prompt(self):
        """config に default があればそれを返す"""
        config_presets = {"default": {"melchior": "カスタムデフォルト"}}
        result = resolve_preset_prompts("default", config_presets)
        self.assertEqual(result, {"melchior": "カスタムデフォルト"})

    def test_unknown_preset_raises_value_error(self):
        """未知のプリセット名は ValueError を送出する"""
        with self.assertRaises(ValueError) as ctx:
            resolve_preset_prompts("nonexistent", None)

        msg = str(ctx.exception)
        self.assertIn("Unknown preset: 'nonexistent'", msg)
        self.assertIn("arch", msg)
        self.assertIn("default", msg)


if __name__ == "__main__":
    unittest.main()
