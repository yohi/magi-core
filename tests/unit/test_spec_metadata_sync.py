import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from magi.core.spec_sync import (
    parse_tasks_markdown,
    summarize_tasks,
    sync_spec_metadata,
)


class TestSpecMetadataSync(unittest.TestCase):
    """spec.json と tasks.md の整合性を検証するテスト。"""

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.tasks_path = self.base / "tasks.md"
        self.spec_path = self.base / "spec.json"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_parse_tasks_without_regex(self) -> None:
        """正規表現を使わずにチェックボックスを機械可読化できること。"""
        content = "\n".join(
            [
                "- [x] 1. 完了タスク",
                "- [ ] 2. 未完了タスク",
                "  - [ ] 2.1 サブタスク",
                "- [ ] タスクIDなし",
            ]
        )
        self.tasks_path.write_text(content, encoding="utf-8")

        records = parse_tasks_markdown(self.tasks_path)
        summary = summarize_tasks(records, self.tasks_path)

        self.assertEqual(len(records), 4)
        self.assertEqual(summary.total_tasks, 4)
        self.assertEqual(summary.completed_tasks, 1)
        self.assertEqual(summary.remaining_tasks, 3)
        self.assertGreaterEqual(summary.completion_rate, 25.0)
        self.assertTrue(summary.last_updated.endswith("Z"))

    def test_sync_updates_spec_and_backup(self) -> None:
        """remaining_tasks とメタデータを原子的に更新できること。"""
        tasks_content = "\n".join(
            [
                "- [x] 1. 完了",
                "- [ ] 2. 未完了",
                "- [ ] 3. 未完了",
            ]
        )
        self.tasks_path.write_text(tasks_content, encoding="utf-8")

        original_spec = {
            "phase_status": {
                "tasks_phase": {
                    "completion_percentage": 10.0,
                    "total_tasks": 5,
                    "completed_tasks": 1,
                    "remaining_tasks": 4,
                    "blocked_tasks": 0,
                }
            },
            "overall_completion_percentage": 10.0,
        }
        self.spec_path.write_text(
            json.dumps(original_spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        time.sleep(0.01)
        result = sync_spec_metadata(
            tasks_path=self.tasks_path,
            spec_path=self.spec_path,
            generator_version="test-cli/1.0.0",
        )

        updated_spec = json.loads(self.spec_path.read_text(encoding="utf-8"))
        backup_path = self.base / "spec.json.bak"

        self.assertTrue(backup_path.exists())
        backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
        self.assertEqual(
            backup_data["phase_status"]["tasks_phase"]["remaining_tasks"], 4
        )

        tasks_phase = updated_spec["phase_status"]["tasks_phase"]
        self.assertEqual(tasks_phase["total_tasks"], 3)
        self.assertEqual(tasks_phase["completed_tasks"], 1)
        self.assertEqual(tasks_phase["remaining_tasks"], 2)
        self.assertAlmostEqual(tasks_phase["completion_percentage"], 33.33, places=1)

        meta = updated_spec["meta"]["tasks_sync"]
        self.assertEqual(meta["synced_from"], "tasks.md")
        self.assertEqual(meta["generator_version"], "test-cli/1.0.0")
        self.assertEqual(meta["status_summary"], "in_progress")
        self.assertEqual(meta["in_progress_count"], 0)
        self.assertEqual(result.remaining_tasks, 2)

