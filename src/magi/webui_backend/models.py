"""
WebUIバックエンド用データモデル
"""

from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Any
import uuid

from pydantic import BaseModel, Field, PrivateAttr

class SessionPhase(str, Enum):
    """セッションのフェーズ定義"""
    QUEUED = "QUEUED"
    THINKING = "THINKING"
    DEBATE = "DEBATE"
    VOTING = "VOTING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"

class UnitType(str, Enum):
    """3賢者のユニット定義"""
    MELCHIOR = "MELCHIOR-1"
    BALTHASAR = "BALTHASAR-2"
    CASPER = "CASPER-3"

class UnitState(str, Enum):
    """ユニットの状態定義"""
    IDLE = "IDLE"
    THINKING = "THINKING"
    DEBATING = "DEBATING"
    VOTING = "VOTING"
    VOTED = "VOTED"

class UnitStatus(BaseModel):
    """ユニットごとの詳細ステータス"""
    type: UnitType
    state: UnitState = UnitState.IDLE
    score: float = 0.0
    message: str = ""

class SessionOptions(BaseModel):
    """セッション作成時のオプション"""
    model: Optional[str] = None
    max_rounds: Optional[int] = None
    timeout_sec: float = 120.0
    attachments: Optional[List[Dict[str, Any]]] = None

class Session(BaseModel):
    """セッション状態を保持するモデル"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    options: SessionOptions
    created_at: datetime = Field(default_factory=datetime.now)
    last_accessed_at: datetime = Field(default_factory=datetime.now)
    phase: SessionPhase = SessionPhase.QUEUED
    progress: int = 0
    
    # 各ユニットの状態
    units: Dict[UnitType, UnitStatus] = Field(default_factory=dict)
    
    # ログ (簡易的な保持。本番ではリングバッファ等を検討)
    logs: List[str] = Field(default_factory=list)
    
    # asyncio.Task は Pydantic の管理外にする
    _task: Optional[Any] = PrivateAttr(default=None)

    def __init__(self, **data):
        super().__init__(**data)
        # ユニット初期化
        if not self.units:
            self.units = {
                UnitType.MELCHIOR: UnitStatus(type=UnitType.MELCHIOR),
                UnitType.BALTHASAR: UnitStatus(type=UnitType.BALTHASAR),
                UnitType.CASPER: UnitStatus(type=UnitType.CASPER),
            }

    def touch(self):
        """最終アクセス時刻を更新"""
        self.last_accessed_at = datetime.now()

    def set_task(self, task):
        """実行タスクをセット"""
        self._task = task

    def get_task(self):
        """実行タスクを取得"""
        return self._task
