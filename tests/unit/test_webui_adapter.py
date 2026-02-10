import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from datetime import datetime

from magi.webui_backend.adapter import MockMagiAdapter, ConsensusEngineMagiAdapter
from magi.webui_backend.models import SessionOptions, UnitType, UnitState
from magi.config.manager import Config
from magi.models import ConsensusResult, ThinkingOutput, DebateRound, VoteOutput, Vote, Decision, PersonaType, ConsensusPhase

class TestMockMagiAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_run_yields_events(self):
        adapter = MockMagiAdapter()
        events = []
        async for event in adapter.run("test prompt", SessionOptions()):
            events.append(event)
        
        self.assertTrue(len(events) > 0)
        self.assertEqual(events[0]["type"], "log")
        self.assertIn("lines", events[0])
        self.assertIsInstance(events[0]["lines"], list)
        
        types = [e["type"] for e in events]
        self.assertIn("phase", types)
        self.assertIn("unit", types)
        self.assertIn("final", types)
        
        final_events = [e for e in events if e["type"] == "final"]
        self.assertEqual(len(final_events), 1)
        self.assertEqual(final_events[0]["decision"], "APPROVE")
        self.assertIn("votes", final_events[0])

class TestConsensusEngineMagiAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = MagicMock(spec=Config)
        self.llm_client_factory = MagicMock()
        self.mock_engine = MagicMock()
        self.mock_engine.streaming_emitter = AsyncMock()
        self.mock_engine.streaming_emitter.aclose = AsyncMock()
        
        self.mock_engine._run_thinking_phase = AsyncMock()
        self.mock_engine._run_debate_phase = AsyncMock()
        self.mock_engine._run_voting_phase = AsyncMock()
        
        self.mock_thinking_result = {
            PersonaType.MELCHIOR: ThinkingOutput(PersonaType.MELCHIOR, "thought", datetime.now())
        }
        self.mock_engine._run_thinking_phase.return_value = self.mock_thinking_result
        
        self.mock_debate_result = [DebateRound(1, {}, datetime.now())]
        self.mock_engine._run_debate_phase.return_value = self.mock_debate_result
        
        self.mock_voting_result = {
            "voting_results": {
                PersonaType.MELCHIOR: VoteOutput(PersonaType.MELCHIOR, Vote.APPROVE, "reason")
            },
            "decision": Decision.APPROVED,
            "exit_code": 0,
            "all_conditions": []
        }
        self.mock_engine._run_voting_phase.return_value = self.mock_voting_result
        
        self.engine_factory = MagicMock(return_value=self.mock_engine)
        
        self.adapter = ConsensusEngineMagiAdapter(
            config=self.config,
            llm_client_factory=self.llm_client_factory,
            engine_factory=self.engine_factory
        )

    async def test_run_orchestration(self):
        async def mock_run_stream(prompt, attachments=None):
            yield {"type": "stream", "content": "thought", "persona": PersonaType.MELCHIOR, "phase": ConsensusPhase.THINKING}
            yield {"type": "event", "event_type": "phase.transition", "payload": {"phase": "DEBATE"}}
            yield {"type": "event", "event_type": "phase.transition", "payload": {"phase": "VOTING"}}
            yield {"type": "result", "data": ConsensusResult(
                thinking_results=self.mock_thinking_result,
                debate_results=self.mock_debate_result,
                voting_results=self.mock_voting_result["voting_results"],
                final_decision=self.mock_voting_result["decision"],
                exit_code=self.mock_voting_result["exit_code"],
                all_conditions=self.mock_voting_result["all_conditions"]
            )}

        self.mock_engine.run_stream.side_effect = mock_run_stream

        events = []
        async for event in self.adapter.run("test prompt", SessionOptions()):
            events.append(event)
            
        self.engine_factory.assert_called_once()
        
        self.mock_engine.run_stream.assert_called_once()
        args, kwargs = self.mock_engine.run_stream.call_args
        self.assertEqual(args[0], "test prompt")
        self.assertIn("attachments", kwargs)
        self.assertIsNone(kwargs["attachments"])
        
        phases = [e["phase"] for e in events if e["type"] == "phase"]
        self.assertEqual(phases, ["THINKING", "DEBATE", "VOTING"])
        
        final_events = [e for e in events if e["type"] == "final"]
        self.assertEqual(len(final_events), 1)
        self.assertEqual(final_events[0]["decision"], "APPROVE")
        self.assertIn("votes", final_events[0])
        self.assertEqual(final_events[0]["votes"]["MELCHIOR-1"]["vote"], "YES")

    async def test_error_handling(self):
        self.mock_engine.run_stream.side_effect = Exception("Test Error")
        
        events = []
        async for event in self.adapter.run("test prompt", SessionOptions()):
            events.append(event)
            
        error_events = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["code"], "MAGI_CORE_ERROR")
        self.assertIn("Test Error", error_events[0]["message"])

    async def test_model_selection(self):
        options = SessionOptions(model="test-model-999", max_rounds=5)
        
        async for _ in self.adapter.run("test prompt", options):
            pass
            
        self.engine_factory.assert_called_once()
        _, kwargs = self.engine_factory.call_args
        run_config = kwargs.get("config")
        
        self.assertEqual(run_config.model, "test-model-999")
        self.assertEqual(run_config.debate_rounds, 5)
