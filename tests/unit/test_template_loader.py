"""TemplateLoader のユニットテスト"""

from datetime import datetime, timedelta
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

    def test_ttl_cache_expires_and_reloads(self):
        """TTL 失効で自動リロードし、失効前はキャッシュを返す"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            tpl = base / "vote_prompt.yaml"
            tpl.write_text(
                "name: vote_prompt\nversion: v1\nschema_ref: vote_schema.json\n"
                "template: \"v1\"\n",
                encoding="utf-8",
            )

            current = [datetime(2025, 1, 1, 0, 0, 0)]

            def now_fn():
                return current[0]

            loader = TemplateLoader(base, ttl_seconds=60, now_fn=now_fn)

            first = loader.load("vote_prompt")
            # TTL 内ではキャッシュを返す
            tpl.write_text(
                "name: vote_prompt\nversion: v2\nschema_ref: vote_schema.json\n"
                "template: \"v2\"\n",
                encoding="utf-8",
            )
            cached = loader.load("vote_prompt")

            self.assertEqual("v1", first.version)
            self.assertEqual("v1", cached.version)

            # TTL 失効後は再読み込みされる
            current[0] = current[0] + timedelta(seconds=120)
            reloaded = loader.load("vote_prompt")

            self.assertEqual("v2", reloaded.version)

    def test_event_hook_receives_reload_and_version_change(self):
        """event_hook に reload/version_changed イベントが通知される"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            tpl = base / "vote_prompt.yaml"
            tpl.write_text(
                "name: vote_prompt\nversion: v1\nschema_ref: vote_schema.json\n"
                "template: \"v1\"\n",
                encoding="utf-8",
            )

            events = []

            def hook(payload):
                events.append(payload)

            loader = TemplateLoader(base, event_hook=hook)
            loader.load("vote_prompt")

            tpl.write_text(
                "name: vote_prompt\nversion: v2\nschema_ref: vote_schema.json\n"
                "template: \"v2\"\n",
                encoding="utf-8",
            )

            loader.reload("vote_prompt", mode="force")

            event_types = [event["type"] for event in events]
            self.assertIn("template.reload", event_types)
            self.assertIn("template.version_changed", event_types)


if __name__ == "__main__":
    unittest.main()
