"""
出力フォーマッタ

合議結果を指定形式（JSON/Markdown）に変換するフォーマッタ
"""

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from magi.models import (
    ConsensusResult,
    Decision,
    PersonaType,
    ThinkingOutput,
    VoteOutput,
    Vote,
    DebateRound,
    DebateOutput,
)


class OutputFormat(Enum):
    """出力形式"""
    JSON = "json"
    MARKDOWN = "markdown"


class OutputFormatter:
    """合議結果を指定形式にフォーマットするクラス"""

    def format(self, result: ConsensusResult, format_type: OutputFormat) -> str:
        """結果を指定形式にフォーマット

        Args:
            result: 合議結果
            format_type: 出力形式

        Returns:
            フォーマットされた文字列
        """
        if format_type == OutputFormat.JSON:
            return self._to_json(result)
        elif format_type == OutputFormat.MARKDOWN:
            return self._to_markdown(result)
        else:
            raise ValueError(f"Unsupported format type: {format_type}")

    def _to_json(self, result: ConsensusResult) -> str:
        """JSON形式に変換

        Args:
            result: 合議結果

        Returns:
            JSON文字列
        """
        data = self._build_output_dict(result)
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _to_markdown(self, result: ConsensusResult) -> str:
        """Markdown形式に変換

        Args:
            result: 合議結果

        Returns:
            Markdown文字列
        """
        lines = []
        
        # ヘッダー
        lines.append("# MAGI 合議結果")
        lines.append("")
        
        # Thinking Phase
        lines.append("## Thinking Phase")
        lines.append("")
        for persona_value, thinking in result.thinking_results.items():
            if isinstance(thinking, ThinkingOutput):
                lines.append(f"### {thinking.persona_type.value.upper()}")
                lines.append("")
                lines.append(thinking.content)
                lines.append("")
        
        # Debate Phase
        lines.append("## Debate Phase")
        lines.append("")
        if result.debate_results:
            for debate_round in result.debate_results:
                lines.append(f"### Round {debate_round.round_number}")
                lines.append("")
                for persona, output in debate_round.outputs.items():
                    lines.append(f"#### {persona.value.upper()}")
                    lines.append("")
                    for target_persona, response in output.responses.items():
                        lines.append(f"**{target_persona.value.upper()}への反論:**")
                        lines.append(response)
                        lines.append("")
        else:
            lines.append("*議論はスキップされました*")
            lines.append("")
        
        # Voting Phase
        lines.append("## Voting Phase")
        lines.append("")
        for persona, vote_output in result.voting_results.items():
            lines.append(f"### {persona.value.upper()}")
            lines.append("")
            lines.append(f"- **投票:** {vote_output.vote.value.upper()}")
            lines.append(f"- **理由:** {vote_output.reason}")
            if vote_output.conditions:
                lines.append("- **条件:**")
                for condition in vote_output.conditions:
                    lines.append(f"  - {condition}")
            lines.append("")
        
        # 最終判定
        lines.append("## 最終判定")
        lines.append("")
        lines.append(f"**{result.final_decision.value.upper()}**")
        lines.append("")
        lines.append(f"Exit Code: {result.exit_code}")
        
        # 条件がある場合
        if result.all_conditions:
            lines.append("")
            lines.append("### 条件一覧")
            lines.append("")
            for condition in result.all_conditions:
                lines.append(f"- {condition}")
        
        return "\n".join(lines)

    def _build_output_dict(self, result: ConsensusResult) -> Dict[str, Any]:
        """出力用の辞書を構築

        Args:
            result: 合議結果

        Returns:
            出力用辞書
        """
        # Thinking結果
        thinking_dict = {}
        for persona_value, thinking in result.thinking_results.items():
            if isinstance(thinking, ThinkingOutput):
                thinking_dict[thinking.persona_type.value] = {
                    "content": thinking.content,
                    "timestamp": thinking.timestamp.isoformat(),
                }
        
        # Debate結果
        debate_list = []
        for debate_round in result.debate_results:
            round_dict = {
                "round_number": debate_round.round_number,
                "outputs": {},
                "timestamp": debate_round.timestamp.isoformat(),
            }
            for persona, output in debate_round.outputs.items():
                round_dict["outputs"][persona.value] = {
                    "responses": {
                        target.value: content
                        for target, content in output.responses.items()
                    },
                }
            debate_list.append(round_dict)
        
        # Voting結果
        voting_dict = {}
        for persona, vote_output in result.voting_results.items():
            voting_dict[persona.value] = {
                "vote": vote_output.vote.value,
                "reason": vote_output.reason,
            }
            if vote_output.conditions:
                voting_dict[persona.value]["conditions"] = vote_output.conditions
        
        # 結果辞書
        output_dict = {
            "thinking_results": thinking_dict,
            "debate_results": debate_list,
            "voting_results": voting_dict,
            "final_decision": result.final_decision.value,
            "exit_code": result.exit_code,
        }
        
        # 条件がある場合
        if result.all_conditions:
            output_dict["conditions"] = result.all_conditions
        
        return output_dict
