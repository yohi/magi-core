"""クオーラム管理ユーティリティ"""

from typing import List, Set

from magi.models import QuorumState


class QuorumManager:
    """クオーラム状態を管理する"""

    def __init__(self, total_agents: int, quorum: int, max_retries: int):
        self.total_agents = total_agents
        self.quorum = quorum
        self.max_retries = max_retries
        self.retries_left = max_retries
        self._excluded: Set[str] = set()
        self._successes: Set[str] = set()

    def note_success(self, persona: str) -> None:
        """成功したペルソナを記録する"""
        self._successes.add(persona)

    def exclude(self, persona: str) -> None:
        """永続的に除外する"""
        self._excluded.add(persona)

    def decrement_retry(self) -> None:
        """残リトライ回数を減らす"""
        if self.retries_left > 0:
            self.retries_left -= 1

    def can_continue(self) -> bool:
        """クオーラムを満たしているか判定"""
        return self.current_alive() >= self.quorum

    def current_alive(self) -> int:
        """有効エージェント数"""
        return self.total_agents - len(self._excluded)

    def current_state(self) -> QuorumState:
        """現在の状態を返す"""
        partial = 0 < len(self._successes) < self.total_agents
        return QuorumState(
            alive=self.current_alive(),
            quorum=self.quorum,
            partial_results=partial,
            retries_left=self.retries_left,
            excluded=sorted(self._excluded),
        )

    def excluded(self) -> List[str]:
        """除外済みのペルソナ一覧"""
        return sorted(self._excluded)
