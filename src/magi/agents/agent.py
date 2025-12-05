"""エージェント実装

個別エージェントの実装。think, debate, voteメソッドを提供する。

Requirements: 3.2, 3.3, 3.4, 4.1
"""
import json
import re
from datetime import datetime
from typing import Dict, Optional

from magi.agents.persona import Persona
from magi.llm.client import LLMClient, LLMRequest
from magi.models import (
    DebateOutput,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
)


class Agent:
    """個別エージェントの実装

    各エージェントはペルソナとLLMクライアントを持ち、
    think、debate、voteの3つの主要メソッドを提供する。

    Attributes:
        persona: エージェントのペルソナ
        llm_client: LLMクライアント
    """

    def __init__(self, persona: Persona, llm_client: LLMClient):
        """Agentを初期化

        Args:
            persona: エージェントのペルソナ
            llm_client: LLMクライアント
        """
        self.persona = persona
        self.llm_client = llm_client

    async def think(self, prompt: str) -> ThinkingOutput:
        """独立した思考を生成

        Thinking Phaseで使用。他のエージェントの出力を参照せず、
        純粋に自分のペルソナに基づいた思考を生成する。

        Args:
            prompt: ユーザーからのプロンプト

        Returns:
            ThinkingOutput: 思考結果
        """
        request = LLMRequest(
            system_prompt=self.persona.system_prompt,
            user_prompt=self._build_thinking_prompt(prompt)
        )

        response = await self.llm_client.send(request)

        return ThinkingOutput(
            persona_type=self.persona.type,
            content=response.content,
            timestamp=datetime.now()
        )

    async def debate(
        self,
        others_thoughts: Dict[PersonaType, str],
        round_num: int
    ) -> DebateOutput:
        """他エージェントの意見に対する反論を生成

        Debate Phaseで使用。他のエージェントの思考結果を参照し、
        それぞれに対する反論や補足意見を生成する。

        Args:
            others_thoughts: 他エージェントの思考内容
            round_num: 現在のラウンド番号

        Returns:
            DebateOutput: 反論結果
        """
        request = LLMRequest(
            system_prompt=self.persona.system_prompt,
            user_prompt=self._build_debate_prompt(others_thoughts, round_num)
        )

        response = await self.llm_client.send(request)

        # レスポンスをパースして各エージェントへの反論を抽出
        responses = self._parse_debate_response(response.content, others_thoughts)

        return DebateOutput(
            persona_type=self.persona.type,
            round_number=round_num,
            responses=responses,
            timestamp=datetime.now()
        )

    async def vote(self, context: str) -> VoteOutput:
        """最終投票を行う

        Voting Phaseで使用。これまでの議論を踏まえて
        APPROVE、DENY、CONDITIONALのいずれかを投票する。

        Args:
            context: これまでの議論のコンテキスト

        Returns:
            VoteOutput: 投票結果
        """
        request = LLMRequest(
            system_prompt=self.persona.system_prompt,
            user_prompt=self._build_vote_prompt(context)
        )

        response = await self.llm_client.send(request)

        # レスポンスをパースして投票結果を抽出
        return self._parse_vote_response(response.content)

    def _build_thinking_prompt(self, prompt: str) -> str:
        """Thinking Phase用のプロンプトを構築

        Args:
            prompt: ユーザーからのプロンプト

        Returns:
            str: 構築されたプロンプト
        """
        return f"""以下の内容について、あなたの視点から分析し、意見を述べてください。

【分析対象】
{prompt}

【指示】
- あなたのペルソナ（{self.persona.name}）の特性に基づいて分析してください
- 他のエージェントの意見は参照せず、独立した思考を行ってください
- 結論と根拠を明確に述べてください"""

    def _build_debate_prompt(
        self,
        others_thoughts: Dict[PersonaType, str],
        round_num: int
    ) -> str:
        """Debate Phase用のプロンプトを構築

        Args:
            others_thoughts: 他エージェントの思考内容
            round_num: 現在のラウンド番号

        Returns:
            str: 構築されたプロンプト
        """
        # 他エージェントの思考を文字列に変換
        thoughts_text = ""
        for persona_type, thought in others_thoughts.items():
            persona_name = self._get_persona_name(persona_type)
            thoughts_text += f"\n【{persona_name}の意見】\n{thought}\n"

        return f"""これはDebate Phase（ラウンド {round_num}）です。

他のエージェントの意見を確認し、反論または補足を行ってください。
{thoughts_text}

【指示】
- 各エージェントの意見に対して、あなたの視点（{self.persona.name}）から反論または補足を述べてください
- 同意できる点と異議がある点を明確にしてください
- 建設的な議論を心がけてください"""

    def _build_vote_prompt(self, context: str) -> str:
        """Voting Phase用のプロンプトを構築

        Args:
            context: これまでの議論のコンテキスト

        Returns:
            str: 構築されたプロンプト
        """
        return f"""これはVoting Phaseです。これまでの議論を踏まえて、最終投票を行ってください。

【これまでの議論】
{context}

【指示】
以下のJSON形式で投票してください：

```json
{{
    "vote": "APPROVE" | "DENY" | "CONDITIONAL",
    "reason": "投票理由を説明してください",
    "conditions": ["条件1", "条件2"]  // CONDITIONALの場合のみ
}}
```

- APPROVE: 提案を承認します
- DENY: 提案を却下します
- CONDITIONAL: 条件付きで承認します（条件を明記してください）

あなたの視点（{self.persona.name}）に基づいて判断してください。"""

    def _get_persona_name(self, persona_type: PersonaType) -> str:
        """PersonaTypeからペルソナ名を取得

        Args:
            persona_type: ペルソナタイプ

        Returns:
            str: ペルソナ名
        """
        name_map = {
            PersonaType.MELCHIOR: "MELCHIOR-1",
            PersonaType.BALTHASAR: "BALTHASAR-2",
            PersonaType.CASPER: "CASPER-3",
        }
        return name_map.get(persona_type, persona_type.value)

    def _parse_debate_response(
        self,
        content: str,
        others_thoughts: Dict[PersonaType, str]
    ) -> Dict[PersonaType, str]:
        """Debateレスポンスをパースして各エージェントへの反論を抽出

        Args:
            content: LLMからのレスポンス内容
            others_thoughts: 他エージェントの思考内容

        Returns:
            Dict[PersonaType, str]: 各エージェントへの反論
        """
        # シンプルなパース：全体を各エージェントへの反論として使用
        # より洗練されたパースは将来の改善点
        responses = {}
        for persona_type in others_thoughts.keys():
            responses[persona_type] = content

        return responses

    def _parse_vote_response(self, content: str) -> VoteOutput:
        """投票レスポンスをパース

        Args:
            content: LLMからのレスポンス内容

        Returns:
            VoteOutput: パースされた投票結果
        """
        try:
            # JSONを抽出（マークダウンコードブロックも考慮）
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # コードブロックがない場合は直接パース試行
                json_str = content

            data = json.loads(json_str)

            # 投票を取得（文字列に変換してからupper()を呼び出す）
            vote_value = data.get("vote")
            if vote_value is None:
                vote_str = ""
            else:
                vote_str = str(vote_value).upper()

            if vote_str == "APPROVE":
                vote = Vote.APPROVE
            elif vote_str == "DENY":
                vote = Vote.DENY
            else:
                vote = Vote.CONDITIONAL

            # 理由を取得
            reason = data.get("reason", "理由なし")

            # 条件を取得（CONDITIONALの場合）
            conditions = None
            if vote == Vote.CONDITIONAL:
                conditions = data.get("conditions", [])

            return VoteOutput(
                persona_type=self.persona.type,
                vote=vote,
                reason=reason,
                conditions=conditions
            )

        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            # パースに失敗した場合はフォールバック
            return VoteOutput(
                persona_type=self.persona.type,
                vote=Vote.CONDITIONAL,
                reason=f"投票レスポンスのパース失敗: {content[:100]}...",
                conditions=None
            )
