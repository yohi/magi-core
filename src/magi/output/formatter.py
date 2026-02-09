"""
出力フォーマッタ

合議結果を指定形式（JSON/Markdown）に変換するフォーマッタ
"""

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

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

    # Colors
    MAGENTA = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    WHITE = '\033[97m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    # Persona Colors - MAGI System Color Pattern
    COLOR_MELCHIOR = '\033[96m'  # シアン - 論理・冷静
    COLOR_BALTHASAR = '\033[93m'  # イエロー - 警戒・注意
    COLOR_CASPER = '\033[95m'  # マゼンタ - 情熱・行動

    # Emojis
    EMOJI_MAGI = "🧠"
    EMOJI_THINKING = "🤔"
    EMOJI_DEBATE = "🗣️"
    EMOJI_VOTE = "🗳️"
    
    EMOJI_MELCHIOR = "🔷"
    EMOJI_BALTHASAR = "🔶"
    EMOJI_CASPER = "🔴"

    EMOJI_APPROVE = "✅"
    EMOJI_DENY = "❌"
    EMOJI_CONDITIONAL = "⚠️"

    def __init__(self, plain: bool = False):
        self.plain = plain

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

    def _get_persona_style(self, persona_name: str) -> Tuple[str, str]:
        """ペルソナに応じた色と絵文字を返す"""
        if self.plain:
            return "", ""

        name = persona_name.lower()
        if "melchior" in name:
            return self.COLOR_MELCHIOR, self.EMOJI_MELCHIOR
        if "balthasar" in name:
            return self.COLOR_BALTHASAR, self.EMOJI_BALTHASAR
        if "casper" in name:
            return self.COLOR_CASPER, self.EMOJI_CASPER
        return self.WHITE, ""

    def _colorize(self, text: str, color: str) -> str:
        """テキストに色を適用する"""
        if self.plain:
            return text
        return f"{color}{text}{self.ENDC}"

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
        title = "MAGI 合議結果" if self.plain else f"{self.EMOJI_MAGI} MAGI 合議結果"
        lines.append(self._colorize(f"# {title}", self.MAGENTA + self.BOLD))
        lines.append("")
        
        # Thinking Phase
        header_text = "Thinking Phase" if self.plain else f"{self.EMOJI_THINKING} Thinking Phase"
        lines.append(self._colorize(f"## {header_text}", self.CYAN + self.BOLD))
        lines.append("")
        for persona_value, thinking in result.thinking_results.items():
            if isinstance(thinking, ThinkingOutput):
                color, emoji = self._get_persona_style(thinking.persona_type.value)
                persona_name = thinking.persona_type.value.upper()
                persona_header = persona_name if self.plain else f"{emoji} {persona_name}"
                lines.append(self._colorize(f"### {persona_header}", color + self.BOLD))
                lines.append("")
                lines.append(thinking.content)
                lines.append("")
        
        # Debate Phase
        header_text = "Debate Phase" if self.plain else f"{self.EMOJI_DEBATE} Debate Phase"
        lines.append(self._colorize(f"## {header_text}", self.GREEN + self.BOLD))
        lines.append("")
        if result.debate_results:
            for debate_round in result.debate_results:
                lines.append(self._colorize(f"### Round {debate_round.round_number}", self.BOLD))
                lines.append("")
                for persona, output in debate_round.outputs.items():
                    color, emoji = self._get_persona_style(persona.value)
                    persona_name = persona.value.upper()
                    persona_header = persona_name if self.plain else f"{emoji} {persona_name}"
                    lines.append(self._colorize(f"#### {persona_header}", color + self.BOLD))
                    lines.append("")
                    for target_persona, response in output.responses.items():
                        target_color, target_emoji = self._get_persona_style(target_persona.value)
                        target_name_str = target_persona.value.upper()
                        target_name = target_name_str if self.plain else f"{target_emoji} {target_name_str}"
                        lines.append(f"**{self._colorize(target_name, target_color)}への反論:**")
                        lines.append(response)
                        lines.append("")
        else:
            lines.append("*議論はスキップされました*")
            lines.append("")
        
        # Voting Phase
        header_text = "Voting Phase" if self.plain else f"{self.EMOJI_VOTE} Voting Phase"
        lines.append(self._colorize(f"## {header_text}", self.YELLOW + self.BOLD))
        lines.append("")
        for persona, vote_output in result.voting_results.items():
            color, emoji = self._get_persona_style(persona.value)
            persona_name = persona.value.upper()
            persona_header = persona_name if self.plain else f"{emoji} {persona_name}"
            lines.append(self._colorize(f"### {persona_header}", color + self.BOLD))
            lines.append("")
            
            vote_val = vote_output.vote.value.upper()
            vote_emoji = ""
            vote_color = self.ENDC
            if not self.plain:
                if vote_val == "APPROVE":
                    vote_emoji = self.EMOJI_APPROVE
                    vote_color = self.GREEN
                elif vote_val == "DENY":
                    vote_emoji = self.EMOJI_DENY
                    vote_color = self.RED
                elif vote_val == "CONDITIONAL":
                    vote_emoji = self.EMOJI_CONDITIONAL
                    vote_color = self.YELLOW
            
            vote_text = vote_val if self.plain else f"{vote_emoji} {self._colorize(vote_val, vote_color)}"
            lines.append(f"- **投票:** {vote_text.strip()}")
            lines.append(f"- **理由:** {vote_output.reason}")
            if vote_output.conditions:
                lines.append("- **条件:**")
                for condition in vote_output.conditions:
                    lines.append(f"  - {condition}")
            lines.append("")
        
        # 最終判定
        lines.append(self._colorize("## 最終判定", self.MAGENTA + self.BOLD))
        lines.append("")
        
        final_decision = result.final_decision.value.upper()
        final_emoji = ""
        final_color = self.ENDC
        if not self.plain:
            if final_decision == "APPROVED":
                final_emoji = self.EMOJI_APPROVE
                final_color = self.GREEN
            elif final_decision == "DENIED":
                final_emoji = self.EMOJI_DENY
                final_color = self.RED
            elif final_decision == "CONDITIONAL":
                final_emoji = self.EMOJI_CONDITIONAL
                final_color = self.YELLOW
            
        final_text = final_decision if self.plain else f"{final_emoji} {self._colorize(final_decision, final_color + self.BOLD)}"
        
        lines.append(f"**{final_text.strip()}**")
        lines.append("")
        lines.append(f"Exit Code: {result.exit_code}")
        
        # 条件がある場合
        if result.all_conditions:
            lines.append("")
            lines.append(self._colorize("### 条件一覧", self.YELLOW + self.BOLD))
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
