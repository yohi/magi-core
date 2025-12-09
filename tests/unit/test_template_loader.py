"""TemplateLoader のユニットテスト"""

import tempfile
import unittest
from pathlib import Path

from magi.core.schema_validator import SchemaValidationError
from magi.core.template_loader import TemplateLoader


class TestTemplateLoader(unittest.TestCase):
    """TemplateLoader の基本動作を確認する"""

    def test_load_yaml_template(self):
        """YAML テンプレートをロードできる"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            tpl = base / "vote_prompt.yaml"
            tpl.write_text(
                "name: vote_prompt\nversion: v1\nschema_ref: vote_schema.json\n"
                "template: \"投票してください: {context}\"\n",
                encoding="utf-8",
            )

            loader = TemplateLoader(base)
            revision = loader.load("vote_prompt")

            self.assertEqual(revision.name, "vote_prompt")
            self.assertEqual(revision.version, "v1")
            self.assertIn("{context}", revision.template)

    def test_reload_force_swaps_version(self):
        """force リロードでキャッシュを置き換える"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            tpl = base / "vote_prompt.yaml"
            tpl.write_text(
                "name: vote_prompt\nversion: v1\nschema_ref: vote_schema.json\n"
                "template: \"old\"\n",
                encoding="utf-8",
            )

            loader = TemplateLoader(base)
            first = loader.load("vote_prompt")

            tpl.write_text(
                "name: vote_prompt\nversion: v2\nschema_ref: vote_schema.json\n"
                "template: \"new\"\n",
                encoding="utf-8",
            )

            second = loader.reload("vote_prompt", mode="force")
            self.assertEqual(first.version, "v1")
            self.assertEqual(second.version, "v2")
            self.assertNotEqual(first.template, second.template)

    def test_validate_template_error(self):
        """必須フィールド不足で例外を送出する"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            tpl = base / "vote_prompt.yaml"
            tpl.write_text("name: only_name\nversion: v1\n", encoding="utf-8")

            loader = TemplateLoader(base)
            with self.assertRaises(SchemaValidationError):
                loader.load("vote_prompt")


if __name__ == "__main__":
    unittest.main()
