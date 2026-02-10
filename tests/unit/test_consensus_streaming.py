import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from magi.core.consensus import ConsensusEngine
from magi.config.manager import Config
from magi.models import ConsensusPhase, ConsensusResult, Decision

class TestConsensusStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_run_stream_yields_events(self):
        config = Config(api_key="test", enable_streaming_output=True)
        engine = ConsensusEngine(config)
        
        # Mock execute to simulate behavior
        async def mock_execute(prompt, plugin=None, attachments=None):
            # Emit some events
            engine._record_event("test.event", value=1)
            
            # Transition phase (which should emit event if we modify it)
            engine._transition_to_phase(ConsensusPhase.DEBATE)
            
            # Emit stream chunk (manually via emitter for test)
            if engine.streaming_emitter:
                await engine.streaming_emitter.emit(
                    "MELCHIOR", 
                    "thinking...", 
                    ConsensusPhase.THINKING.value,
                    round_number=1
                )
                
            return ConsensusResult(
                thinking_results={},
                debate_results=[],
                voting_results={},
                final_decision=Decision.APPROVED,
                exit_code=0,
                all_conditions=[]
            )

        with patch.object(engine, 'execute', side_effect=mock_execute):
            events = []
            async for event in engine.run_stream("test prompt"):
                events.append(event)
                
            # Verify we got events
            event_types = [e.get("event_type") for e in events if e.get("type") == "event"]
            self.assertIn("test.event", event_types)
            self.assertIn("phase.transition", event_types)
            
            # Verify we got stream chunks
            stream_chunks = [e for e in events if e.get("type") == "stream"]
            self.assertTrue(len(stream_chunks) > 0)
            self.assertEqual(stream_chunks[0]["content"], "thinking...")
            self.assertEqual(stream_chunks[0]["round"], 1)
            
            # Verify result
            results = [e for e in events if e.get("type") == "result"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["data"].final_decision, Decision.APPROVED)

    async def test_phase_transition_event(self):
        """_transition_to_phaseがイベントを発火することを確認"""
        config = Config(api_key="test")
        engine = ConsensusEngine(config)
        
        engine._transition_to_phase(ConsensusPhase.DEBATE)
        
        # Check events
        self.assertTrue(len(engine.events) > 0)
        self.assertEqual(engine.events[-1]["type"], "phase.transition")
        self.assertEqual(engine.events[-1]["phase"], ConsensusPhase.DEBATE.value)
