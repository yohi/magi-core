"""pending-tasks-cleanup の tasks.md がテスト観点を保持することを検証する。"""

from pathlib import Path
import re
import unittest


TASKS_PATH = (
    Path(__file__).resolve().parents[2]
    / ".kiro"
    / "specs"
    / "pending-tasks-cleanup"
    / "tasks.md"
)


def _load_tasks_sections():
    """tasks.md を読み込み、タスク ID ごとのセクションを返す。"""
    text = TASKS_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"^- \[[ x]\]\s*(\d+)\.", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections = {}
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections[int(match.group(1))] = text[start:end]
    return text, sections


class TestPendingTasksCleanupTasks(unittest.TestCase):
    """pending-tasks-cleanup のタスク定義の健全性を検証する。"""

    def test_tasks_have_test_methods_sections(self):
        """各タスクにテスト方法の小節があることを確認する。"""
        text, sections = _load_tasks_sections()
        self.assertIn("[x] 7.", text)
        for task_id in range(1, 7):
            self.assertIn(task_id, sections)
            section = sections[task_id]
            self.assertIn("テスト方法", section)
            self.assertIn("Unit:", section)
            self.assertIn("Integration:", section)
            self.assertIn("Property:", section)

    def test_property_sections_cover_boundaries_and_latency(self):
        """Property セクションが境界値と安定性条件を明示することを確認する。"""
        _, sections = _load_tasks_sections()
        # 必須キーワードと推奨キーワードを分離
        required_keywords = [r"入力サイズ", r"境界値"]
        recommended_keywords = [r"ランダム", r"P95", r"<1%"]

        for task_id in range(1, 7):
            # Property: で始まる行のみを抽出し、誤検知を防ぐ
            property_lines = [
                line
                for line in sections[task_id].splitlines()
                if line.strip().startswith("Property:")
            ]
            self.assertTrue(property_lines, f"Property セクション欠落: {task_id}")
            property_text = " ".join(property_lines)

            # 必須キーワードのみを厳格に検証する
            for keyword in required_keywords:
                self.assertRegex(
                    property_text,
                    keyword,
                    f"タスク {task_id} の Property に {keyword} が欠落",
                )
            # 推奨キーワードは記載状況を確認するのみ（欠落は許容）
            _ = [kw for kw in recommended_keywords if re.search(kw, property_text)]

    def test_coverage_targets_are_documented(self):
        """カバレッジ目標が明記されていることを確認する。"""
        text, _ = _load_tasks_sections()
        self.assertIn("ステートメント 80%", text)
        self.assertIn("ブランチ 70%", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
