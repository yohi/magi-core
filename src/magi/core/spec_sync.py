"""
spec.json と tasks.md のメタデータ整合を管理するユーティリティ。

正規表現に頼らずチェックボックスを機械可読に解析し、remaining_tasks を算出して
spec.json を原子的に更新する。バックアップ・fsync・リネームで安全に書き換える。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

try:
    import fcntl  # POSIX 環境でのみ利用
except ImportError:  # pragma: no cover - Windows など
    fcntl = None


@dataclass
class TaskRecord:
    """Markdown チェックボックス 1 件分の情報。"""

    identifier: str
    title: str
    status: str  # completed | pending | in_progress


@dataclass
class TasksSummary:
    """tasks.md 全体の集計結果。"""

    total_tasks: int
    completed_tasks: int
    in_progress_count: int
    remaining_tasks: int
    completion_rate: float
    last_updated: str


@dataclass
class SyncResult:
    """同期結果の返却用データ。"""

    spec_path: Path
    backup_path: Path
    remaining_tasks: int
    completion_rate: float
    synced_at: str


def _extract_status(token: str) -> str:
    """チェックボックス表記から状態を抽出する。"""
    lowered = token.lower()
    if lowered == "x":
        return "completed"
    if lowered == "-":
        return "in_progress"
    return "pending"


def _extract_identifier_and_title(line: str, start_index: int) -> tuple[str, str]:
    """タスク ID とタイトルを正規表現なしで切り出す。"""
    segment = line[start_index:].strip()
    idx = 0
    digits = []
    while idx < len(segment) and segment[idx].isdigit():
        digits.append(segment[idx])
        idx += 1
    # 区切りのドットを読み飛ばす
    if idx < len(segment) and segment[idx] == ".":
        idx += 1
    identifier = "".join(digits) if digits else ""
    title = segment[idx:].strip()
    return identifier, title or segment.strip()


def parse_tasks_markdown(tasks_path: Path) -> List[TaskRecord]:
    """
    tasks.md からチェックボックスを抽出する。

    - 先頭が "- [" で始まる行のみ対象とし、正規表現は使用しない。
    - ステータスは [x]=completed, [-]=in_progress, それ以外は pending とする。
    """
    records: List[TaskRecord] = []
    lines = tasks_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("- ["):
            continue
        closing = stripped.find("]")
        if closing == -1 or len(stripped) < 4:
            continue
        status_token = stripped[3]
        status = _extract_status(status_token)
        identifier, title = _extract_identifier_and_title(stripped, closing + 1)
        if not identifier:
            identifier = str(len(records) + 1)
        records.append(TaskRecord(identifier=identifier, title=title, status=status))
    return records


def summarize_tasks(records: Iterable[TaskRecord], tasks_path: Path) -> TasksSummary:
    """TaskRecord 群から集計情報を算出する。"""
    record_list = list(records)
    total = len(record_list)
    completed = len([r for r in record_list if r.status == "completed"])
    in_progress = len([r for r in record_list if r.status == "in_progress"])
    remaining = total - completed
    rate = round((completed / total) * 100, 2) if total else 0.0

    mtime = datetime.fromtimestamp(tasks_path.stat().st_mtime, tz=timezone.utc)
    last_updated = mtime.isoformat().replace("+00:00", "Z")
    return TasksSummary(
        total_tasks=total,
        completed_tasks=completed,
        in_progress_count=in_progress,
        remaining_tasks=remaining,
        completion_rate=rate,
        last_updated=last_updated,
    )


def _prepare_backup(spec_path: Path) -> Path:
    """バックアップを作成してパスを返す。"""
    backup_path = spec_path.with_suffix(spec_path.suffix + ".bak")
    backup_path.write_text(spec_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def _atomic_write_json(target: Path, content: dict, lock: bool = True) -> None:
    """fsync とリネームによる原子的な JSON 書き込み。"""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=target.name, dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(content, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())

        if lock and fcntl is not None:
            with open(target, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                os.replace(temp_path, target)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        else:
            os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _build_status_summary(remaining_tasks: int, in_progress_count: int) -> str:
    """状態を簡潔なサマリーに変換する。"""
    if remaining_tasks == 0:
        return "done"
    if in_progress_count > 0:
        return "in_progress"
    return "pending"


def sync_spec_metadata(
    tasks_path: Path,
    spec_path: Path,
    *,
    generator_version: str = "magi-cli",
    use_lock: bool = True,
) -> SyncResult:
    """
    tasks.md の内容を読み取り、spec.json の remaining_tasks を同期する。

    - tasks.md は正規表現なしでチェックボックスを抽出する。
    - 更新前に spec.json.bak を作成し、失敗時はバックアップを維持する。
    - fsync + rename（必要に応じて advisory lock）で原子的に更新する。
    """
    records = parse_tasks_markdown(tasks_path)
    summary = summarize_tasks(records, tasks_path)

    if not spec_path.exists():
        raise FileNotFoundError(f"spec.json が見つかりません: {spec_path}")

    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    backup_path = _prepare_backup(spec_path)

    phase_status = spec_data.setdefault("phase_status", {}).setdefault(
        "tasks_phase", {}
    )
    phase_status["total_tasks"] = summary.total_tasks
    phase_status["completed_tasks"] = summary.completed_tasks
    phase_status["remaining_tasks"] = summary.remaining_tasks
    phase_status["completion_percentage"] = summary.completion_rate
    phase_status.setdefault("blocked_tasks", 0)

    spec_data.setdefault("meta", {})
    spec_data["meta"]["tasks_sync"] = {
        "synced_from": "tasks.md",
        "synced_at": summary.last_updated,
        "generator_version": generator_version,
        "status_summary": _build_status_summary(
            summary.remaining_tasks, summary.in_progress_count
        ),
        "in_progress_count": summary.in_progress_count,
        "completion_rate": summary.completion_rate,
    }

    _atomic_write_json(spec_path, spec_data, lock=use_lock)

    return SyncResult(
        spec_path=spec_path,
        backup_path=backup_path,
        remaining_tasks=summary.remaining_tasks,
        completion_rate=summary.completion_rate,
        synced_at=summary.last_updated,
    )

