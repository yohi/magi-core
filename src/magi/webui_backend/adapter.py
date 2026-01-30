"""
MagiAdapterの実装

WebUIとMagi Core（ConsensusEngine）を接続するためのアダプターインターフェースと実装を提供する。
"""
import asyncio
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
        queue: asyncio.Queue = asyncio.Queue()
        
        async def _bridge_send(chunk: StreamChunk):
            unit_type = self._map_persona_to_unit(chunk.persona)
            if unit_type:
                await queue.put({
                    "type": "unit",
                    "unit": unit_type.value,
                    "state": self._map_phase_to_unit_state(chunk.phase).value,
                    "message": chunk.chunk,
                    "stream": True
                })

        def _on_event(event_type: str, payload: Dict[str, Any]):
            if event_type in ("streaming.drop", "streaming.timeout"):
                reason = payload.get("reason", "unknown")
                asyncio.create_task(queue.put({
                    "type": "log",
                    "lines": [f"Streaming warning: {event_type} ({reason})"],
                    "level": "WARN"
                }))

        emitter = QueueStreamingEmitter(
            send_func=_bridge_send,
            queue_size=100,
            emit_timeout_seconds=2.0,
            on_event=_on_event
        )
        
        run_config = self.config
        if options.max_rounds is not None:
            # UIオプションのmax_roundsをrun_configに反映
            run_config.debate_rounds = int(options.max_rounds)

        async def _run_engine():
            engine = None
            try:
                engine = self.engine_factory(
                    config=run_config,
                    llm_client_factory=self.llm_client_factory,
                    streaming_emitter=emitter
                )
                
                await queue.put({"type": "phase", "phase": "THINKING"})
                await queue.put({"type": "progress", "pct": 10})
                
                thinking_results = await engine._run_thinking_phase(prompt)
                
                await queue.put({"type": "phase", "phase": "DEBATE"})
                await queue.put({"type": "progress", "pct": 40})
                
                debate_results = await engine._run_debate_phase(
                    thinking_results, close_streaming=False
                )
                
                await queue.put({"type": "phase", "phase": "VOTING"})
                await queue.put({"type": "progress", "pct": 80})
                
                voting_result_dict = await engine._run_voting_phase(
                    thinking_results, debate_results
                )
                
                str_thinking_results = {
                    k.value if hasattr(k, "value") else str(k): v 
                    for k, v in thinking_results.items()
                }

                result = ConsensusResult(
                    thinking_results=str_thinking_results,
                    debate_results=debate_results,
                    voting_results=voting_result_dict["voting_results"],
                    final_decision=voting_result_dict["decision"],
                    exit_code=voting_result_dict["exit_code"],
                    all_conditions=voting_result_dict["all_conditions"]
                )
                
                await queue.put({"type": "progress", "pct": 100})
                
                final_payload = self._build_final_payload(result)
                await queue.put(final_payload)
                
            except Exception as e:
                logger.exception("ConsensusEngine execution failed")
                await queue.put({
                    "type": "error",
                    "code": "MAGI_CORE_ERROR",
                    "message": str(e)
                })
            finally:
                if engine and engine.streaming_emitter:
                    await engine.streaming_emitter.aclose()
                await queue.put(None)

        task = asyncio.create_task(_run_engine())
        
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            # ジェネレータが早期終了した場合でもタスクをクリーンアップ
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # キャンセルは想定内
                pass
            except Exception as e:
                # その他の例外はログに記録
                logger.exception("Background task cleanup failed: %s", e)

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
