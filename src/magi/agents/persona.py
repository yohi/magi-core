"""ペルソナ管理

3賢者のペルソナを定義・管理するモジュール。

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""
from dataclasses import dataclass
from typing import Dict, Optional

from magi.models import PersonaType


# MELCHIOR-1の基本プロンプト（論理・科学担当）
MELCHIOR_BASE_PROMPT = """あなたはMAGIシステムのMELCHIOR-1です。
論理と科学を担当するエージェントとして、以下の役割を果たします：

1. 論理的整合性の分析
   - 提案された内容の論理的な矛盾を検出
   - 因果関係の妥当性を評価
   - 前提条件の明確化

2. 事実に基づいた分析
   - 客観的なデータや証拠に基づく評価
   - 技術的な正確性の確認
   - 実現可能性の検証

3. 科学的アプローチ
   - 仮説と検証の明確化
   - 再現可能性の考慮
   - エビデンスに基づく推論

常に冷静かつ客観的な視点を維持し、感情や主観に左右されない分析を提供してください。"""

# BALTHASAR-2の基本プロンプト（倫理・保護担当）
BALTHASAR_BASE_PROMPT = """あなたはMAGIシステムのBALTHASAR-2です。
倫理と保護を担当するエージェントとして、以下の役割を果たします：

1. リスク回避
   - 潜在的な危険性の特定
   - 最悪のシナリオの検討
   - 安全マージンの確保

2. 現状維持の視点
   - 変更による影響の評価
   - 既存システムとの整合性
   - 後戻りの可能性の確認

3. 倫理的考慮
   - ステークホルダーへの影響
   - 公平性と透明性
   - 長期的な責任

常に慎重かつ保守的な視点を維持し、潜在的なリスクを見逃さないよう注意してください。"""

# CASPER-3の基本プロンプト（欲望・実利担当）
CASPER_BASE_PROMPT = """あなたはMAGIシステムのCASPER-3です。
欲望と実利を担当するエージェントとして、以下の役割を果たします：

1. ユーザー利益の最優先
   - ユーザーが本当に求めているものを理解
   - 期待を超える価値の提案
   - ユーザー体験の最適化

2. 効率性の追求
   - 時間とリソースの最適化
   - 過度な複雑さの排除
   - 実用的な解決策の提示

3. 実利的アプローチ
   - 具体的なメリットの提示
   - コストパフォーマンスの評価
   - 迅速な成果の重視

常に前向きかつ実践的な視点を維持し、ユーザーの目標達成を最優先で考えてください。"""


@dataclass
class Persona:
    """ペルソナデータクラス

    3賢者の各ペルソナを表現する。

    Attributes:
        type: ペルソナタイプ（MELCHIOR/BALTHASAR/CASPER）
        name: ペルソナ名（例: "MELCHIOR-1"）
        base_prompt: 基本システムプロンプト
        override_prompt: プラグインからの追加指示
    """
    type: PersonaType
    name: str
    base_prompt: str
    override_prompt: Optional[str] = None

    @property
    def system_prompt(self) -> str:
        """基本プロンプトとオーバーライドを結合したシステムプロンプトを返す

        Returns:
            str: 完全なシステムプロンプト
        """
        if self.override_prompt:
            return f"{self.base_prompt}\n\n{self.override_prompt}"
        return self.base_prompt


class PersonaManager:
    """3賢者のペルソナを管理するマネージャー

    Requirements:
        - 3.1: MELCHIOR-1、BALTHASAR-2、CASPER-3の3つのペルソナを生成
        - 3.2: MELCHIOR-1は論理的整合性と事実に基づいた分析を出力
        - 3.3: BALTHASAR-2はリスク回避と潜在的危険性の指摘を出力
        - 3.4: CASPER-3はユーザー利益と効率性の観点からの評価を出力
        - 3.5: プラグイン固有の指示を追加しながら基本特性を維持
    """

    # ペルソナ名のマッピング
    _PERSONA_NAME_MAP = {
        PersonaType.MELCHIOR: "MELCHIOR-1",
        PersonaType.BALTHASAR: "BALTHASAR-2",
        PersonaType.CASPER: "CASPER-3",
    }

    # ペルソナの基本プロンプトマッピング
    _BASE_PROMPT_MAP = {
        PersonaType.MELCHIOR: MELCHIOR_BASE_PROMPT,
        PersonaType.BALTHASAR: BALTHASAR_BASE_PROMPT,
        PersonaType.CASPER: CASPER_BASE_PROMPT,
    }

    # 文字列キーからPersonaTypeへのマッピング
    _STRING_TO_TYPE = {
        "melchior": PersonaType.MELCHIOR,
        "balthasar": PersonaType.BALTHASAR,
        "casper": PersonaType.CASPER,
    }

    def __init__(self):
        """PersonaManagerを初期化

        3つのペルソナ（MELCHIOR、BALTHASAR、CASPER）を生成する。
        """
        self.personas: Dict[PersonaType, Persona] = {}
        self._initialize_personas()

    def _initialize_personas(self) -> None:
        """3つのペルソナを初期化"""
        for persona_type in PersonaType:
            self.personas[persona_type] = Persona(
                type=persona_type,
                name=self._PERSONA_NAME_MAP[persona_type],
                base_prompt=self._BASE_PROMPT_MAP[persona_type]
            )

    def get_persona(self, persona_type: PersonaType) -> Persona:
        """指定されたペルソナを取得

        Args:
            persona_type: 取得するペルソナのタイプ

        Returns:
            Persona: 指定されたペルソナ
        """
        return self.personas[persona_type]

    def apply_overrides(self, overrides: Dict[str, str]) -> None:
        """プラグインからのオーバーライドを適用

        Args:
            overrides: ペルソナ名（小文字）をキー、オーバーライドプロンプトを値とする辞書
                      例: {"melchior": "追加指示", "balthasar": "追加指示"}
        """
        for persona_name, override_prompt in overrides.items():
            # 文字列キーをPersonaTypeに変換
            persona_type = self._STRING_TO_TYPE.get(persona_name.lower())
            if persona_type is None:
                # 未知のペルソナ名は無視
                continue

            # 既存のペルソナを取得し、オーバーライドを適用した新しいペルソナを作成
            existing = self.personas[persona_type]
            self.personas[persona_type] = Persona(
                type=existing.type,
                name=existing.name,
                base_prompt=existing.base_prompt,
                override_prompt=override_prompt
            )

    def clear_overrides(self) -> None:
        """全てのペルソナのオーバーライドをクリア"""
        for persona_type in PersonaType:
            existing = self.personas[persona_type]
            if existing.override_prompt is not None:
                self.personas[persona_type] = Persona(
                    type=existing.type,
                    name=existing.name,
                    base_prompt=existing.base_prompt,
                    override_prompt=None
                )
