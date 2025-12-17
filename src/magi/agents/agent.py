"""エージェント実装

個別エージェントの実装。think, debate, voteメソッドを提供する。

Requirements: 3.2, 3.3, 3.4, 4.1
"""
import json
import logging
import re
from datetime import datetime
from typing import Dict, Optional

from magi.agents.persona import Persona
from magi.core.schema_validator import (
    SchemaValidationError,
    SchemaValidator,
)
from magi.core.template_loader import TemplateLoader
from magi.core.token_budget import (
    TokenBudgetExceeded,
    TokenBudgetManagerProtocol,
)
from magi.errors import MagiException, create_agent_error
from magi.llm.client import LLMClient, LLMRequest
from magi.models import (
    DebateOutput,
    PersonaType,
    ThinkingOutput,
    Vote,
    VoteOutput,
)
from magi.security.filter import SecurityFilter

logger = logging.getLogger(__name__)


class Agent:
    """個別エージェントの実装

    各エージェントはペルソナとLLMクライアントを持ち、
    think、debate、voteの3つの主要メソッドを提供する。

    Attributes:
        persona: エージェントのペルソナ
        llm_client: LLMクライアント
    """

    def __init__(
        self,
        persona: Persona,
        llm_client: LLMClient,
        schema_validator: Optional[SchemaValidator] = None,
        template_loader: Optional[TemplateLoader] = None,
        security_filter: Optional[SecurityFilter] = None,
        token_budget_manager: Optional[TokenBudgetManagerProtocol] = None,
    ):
        """Agentを初期化

        Args:
            persona: エージェントのペルソナ
            llm_client: LLMクライアント
        """
        self.persona = persona
        self.llm_client = llm_client
        self.schema_validator = schema_validator or SchemaValidator()
        self.template_loader = template_loader
        self.security_filter = security_filter or SecurityFilter()
        self.token_budget_manager = token_budget_manager

    def _estimate_tokens(self, text: str) -> int:
        """トークン数を推定する."""
        if self.token_budget_manager and hasattr(
            self.token_budget_manager, "estimate_tokens"
        ):
            try:
                return int(self.token_budget_manager.estimate_tokens(text))
            except Exception:  # pragma: no cover - フォールバック用途
                logger.debug("estimate_tokens failed; fallback to len", exc_info=True)
        return len(text)

    def _enforce_budget(self, request_text: str) -> None:
        """予算超過時に例外を送出する."""
        if self.token_budget_manager is None:
            return
        estimated = self._estimate_tokens(request_text)
        allowed = self.token_budget_manager.check_budget(estimated)
        if not allowed:
            max_tokens = getattr(self.token_budget_manager, "max_tokens", None)
            raise TokenBudgetExceeded(
                estimated_tokens=estimated,
                max_tokens=max_tokens,
            )

    def _record_consumption(self, response_text: str) -> None:
        """レスポンスの消費トークンを記録する."""
        if self.token_budget_manager is None:
            return
        try:
            tokens = self._estimate_tokens(response_text)
            self.token_budget_manager.consume(tokens)
        except Exception:  # pragma: no cover - 記録失敗は致命的でない
            logger.debug("token consume failed; ignoring", exc_info=True)

    async def think(self, prompt: str) -> ThinkingOutput:
        """独立した思考を生成

        Thinking Phaseで使用。他のエージェントの出力を参照せず、
        純粋に自分のペルソナに基づいた思考を生成する。

        Args:
            prompt: ユーザーからのプロンプト

        Returns:
            ThinkingOutput: 思考結果
        """
        sanitized = self.security_filter.sanitize_prompt(prompt)
        if sanitized.blocked:
            raise MagiException(
                create_agent_error(
                    "ユーザー入力に禁止パターンが含まれています。",
                    details={"rules": sanitized.matched_rules},
                )
            )
        request = LLMRequest(
            system_prompt=self.persona.system_prompt,
            user_prompt=self._build_thinking_prompt(sanitized.safe)
        )

        self._enforce_budget(f"{request.system_prompt}\n{request.user_prompt}")
        response = await self.llm_client.send(request)
        self._record_consumption(response.content)

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

        self._enforce_budget(f"{request.system_prompt}\n{request.user_prompt}")
        response = await self.llm_client.send(request)
        self._record_consumption(response.content)

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

        self._enforce_budget(f"{request.system_prompt}\n{request.user_prompt}")
        response = await self.llm_client.send(request)
        self._record_consumption(response.content)

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
        if self.template_loader:
            try:
                revision = self.template_loader.load("vote_prompt")
                variables = revision.variables or {}
                variables = {**variables, "context": context}
                return revision.template.format(**variables)
            except Exception as exc:
                logger.warning("投票テンプレートの読み込みに失敗しました: %s", exc)

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
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = content

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError([f"JSONのデコードに失敗しました: {exc}"]) from exc

        validation = self.schema_validator.validate_vote_payload(data)
        if not validation.ok:
            raise SchemaValidationError(validation.errors)

        vote_raw = data["vote"]
        vote_str = str(vote_raw).strip().upper()
        vote_map = {
            "APPROVE": Vote.APPROVE,
            "DENY": Vote.DENY,
            "CONDITIONAL": Vote.CONDITIONAL,
        }
        try:
            vote = vote_map[vote_str]
        except KeyError as exc:
            logger.error(
                "無効な投票値を受信しました: original=%r normalized=%s",
                vote_raw,
                vote_str,
            )
            raise ValueError(
                f"投票値が不正です: original={vote_raw!r} normalized={vote_str}"
            ) from exc

        conditions = None
        if vote == Vote.CONDITIONAL:
            conditions = data.get("conditions", [])

        return VoteOutput(
            persona_type=self.persona.type,
            vote=vote,
            reason=data["reason"],
            conditions=conditions,
        )
