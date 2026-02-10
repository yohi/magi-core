"""
MagiAdapterの実装

WebUIとMagi Core（ConsensusEngine）を接続するためのアダプターインターフェースと実装を提供する。
"""
import asyncio
import copy
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Callable, Dict, Optional

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.core.streaming import StreamChunk, QueueStreamingEmitter
from magi.models import ConsensusPhase, Decision, PersonaType, Vote, ConsensusResult
from magi.webui_backend.models import SessionOptions, UnitType, UnitState

logger = logging.getLogger(__name__)

class MagiAdapter(ABC):
    """Magi Coreを実行し、イベントストリームを生成するアダプターインターフェース"""

    @abstractmethod
    async def run(self, prompt: str, options: SessionOptions) -> AsyncIterator[Dict[str, Any]]:
        """Magiを実行し、イベントを非同期にyieldする"""
        pass
        yield {}


class MockMagiAdapter(MagiAdapter):
    """WebUI開発用のモックアダプター"""

    async def run(self, prompt: str, options: SessionOptions) -> AsyncIterator[Dict[str, Any]]:
        yield {
            "type": "log",
            "lines": ["セッションを開始します..."],
            "level": "INFO"
        }
        
        yield {"type": "phase", "phase": "THINKING"}
        yield {"type": "progress", "pct": 10}
        
        units = [UnitType.MELCHIOR, UnitType.BALTHASAR, UnitType.CASPER]
        for unit in units:
            yield {
                "type": "unit",
                "unit": unit.value,
                "state": UnitState.THINKING.value,
                "message": f"{unit.value} is thinking...",
                "score": 0.0
            }
        
        await asyncio.sleep(1)
        yield {"type": "progress", "pct": 30}
        
        yield {"type": "phase", "phase": "DEBATE"}
        for round_num in range(1, (options.max_rounds or 1) + 1):
            yield {
                "type": "log",
                "lines": [f"Debate Round {round_num} started"],
                "level": "INFO"
            }
            yield {"type": "progress", "pct": 30 + (round_num * 10)}
            
            for unit in units:
                yield {
                    "type": "unit",
                    "unit": unit.value,
                    "state": UnitState.DEBATING.value,
                    "message": f"{unit.value} is debating (Round {round_num})...",
                    "score": 0.0
                }
            await asyncio.sleep(1)

        yield {"type": "phase", "phase": "VOTING"}
        yield {"type": "progress", "pct": 90}
        
        for unit in units:
            yield {
                "type": "unit",
                "unit": unit.value,
                "state": UnitState.VOTING.value,
                "message": f"{unit.value} is voting...",
                "score": 0.0
            }
        
        await asyncio.sleep(0.5)
        
        decision = "APPROVE"
        voting_results = {
            "MELCHIOR-1": {"vote": "YES", "reason": "Logical approval"},
            "BALTHASAR-2": {"vote": "YES", "reason": "Safe to proceed"},
            "CASPER-3": {"vote": "YES", "reason": "Beneficial"}
        }
        
        yield {"type": "progress", "pct": 100}
        yield {
            "type": "final",
            "decision": decision,
            "votes": voting_results,
            "summary": "Mock execution completed successfully.",
            "result": {
                "decision": decision,
                "voting_results": voting_results,
                "exit_code": 0
            }
        }


class ConsensusEngineMagiAdapter(MagiAdapter):
    """ConsensusEngineを直接呼び出すアダプター"""

    def __init__(
        self,
        config: Config,
        llm_client_factory: Optional[Callable] = None,
        engine_factory: Optional[Callable[..., ConsensusEngine]] = None,
    ):
        self.config = config
        self.llm_client_factory = llm_client_factory
        self.engine_factory = engine_factory or ConsensusEngine

    async def run(self, prompt: str, options: SessionOptions) -> AsyncIterator[Dict[str, Any]]:
        # 設定のディープコピーを作成して、セッション固有の設定として扱う
        run_config = copy.deepcopy(self.config)
        if options.model is not None:
            run_config.model = options.model
        if options.max_rounds is not None:
            run_config.debate_rounds = int(options.max_rounds)

        engine = None
        try:
            logger.info("Initializing ConsensusEngine")
            engine = self.engine_factory(
                config=run_config,
                llm_client_factory=self.llm_client_factory,
                # run_streamが内部でemitterを設定するため、ここではNoneでよいが、
                # コンストラクタの互換性のために渡す必要があれば渡す（通常はNoneでOK）
                streaming_emitter=None
            )

            # 初期状態の送信
            yield {"type": "phase", "phase": "THINKING"}
            yield {"type": "progress", "pct": 5}

            async for event in engine.run_stream(prompt):
                if event["type"] == "stream":
                    unit_type = self._map_persona_to_unit(event["persona"])
                    if unit_type:
                        yield {
                            "type": "unit",
                            "unit": unit_type.value,
                            "state": self._map_phase_to_unit_state(event["phase"]).value,
                            "message": event["content"],
                            "stream": True
                        }
                
                elif event["type"] == "event":
                    event_type = event["event_type"]
                    payload = event["payload"]
                    
                    if event_type == "phase.transition":
                        phase_val = str(payload.get("phase", "")).upper()
                        yield {"type": "phase", "phase": phase_val}
                        
                        # フェーズに応じた進捗更新
                        if "THINKING" in phase_val:
                            yield {"type": "progress", "pct": 10}
                        elif "DEBATE" in phase_val:
                            yield {"type": "progress", "pct": 40}
                        elif "VOTING" in phase_val:
                            yield {"type": "progress", "pct": 80}
                        elif "COMPLETED" in phase_val:
                            yield {"type": "progress", "pct": 100}
                    
                    elif event_type in ("streaming.drop", "streaming.timeout"):
                        reason = payload.get("reason", "unknown")
                        yield {
                            "type": "log",
                            "lines": [f"Streaming warning: {event_type} ({reason})"],
                            "level": "WARN"
                        }

                elif event["type"] == "result":
                    result = event["data"]
                    yield self._build_final_payload(result)

        except Exception as e:
            logger.exception("ConsensusEngine execution failed")
            yield {
                "type": "error",
                "code": "MAGI_CORE_ERROR",
                "message": str(e)
            }

    def _map_persona_to_unit(self, persona: Any) -> Optional[UnitType]:
        val = persona.value if hasattr(persona, "value") else str(persona)
        if val == PersonaType.MELCHIOR.value:
            return UnitType.MELCHIOR
        elif val == PersonaType.BALTHASAR.value:
            return UnitType.BALTHASAR
        elif val == PersonaType.CASPER.value:
            return UnitType.CASPER
        return None

    def _map_phase_to_unit_state(self, phase: Any) -> UnitState:
        val = phase.value if hasattr(phase, "value") else str(phase)
        if val == ConsensusPhase.THINKING.value:
            return UnitState.THINKING
        elif val == ConsensusPhase.DEBATE.value:
            return UnitState.DEBATING
        elif val == ConsensusPhase.VOTING.value:
            return UnitState.VOTING
        return UnitState.IDLE

    def _build_final_payload(self, result: ConsensusResult) -> Dict[str, Any]:
        decision_map = {
            Decision.APPROVED: "APPROVE",
            Decision.DENIED: "DENY",
            Decision.CONDITIONAL: "CONDITIONAL"
        }
        decision_str = decision_map.get(result.final_decision, "DENY")

        vote_map = {
            Vote.APPROVE: "YES",
            Vote.DENY: "NO",
            Vote.CONDITIONAL: "ABSTAIN"
        }
        
        voting_results_payload = {}
        for persona, vote_output in result.voting_results.items():
            unit = self._map_persona_to_unit(persona)
            if unit:
                voting_results_payload[unit.value] = {
                    "vote": vote_map.get(vote_output.vote, "NO"),
                    "reason": vote_output.reason
                }

        return {
            "type": "final",
            "decision": decision_str,
            "votes": voting_results_payload,
            "summary": f"Decision: {decision_str}",
            "result": {
                "decision": decision_str,
                "voting_results": voting_results_payload,
                "exit_code": result.exit_code
            }
        }
