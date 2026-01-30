
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from magi.webui_backend.session_manager import SessionManager
from magi.webui_backend.models import SessionOptions, SessionPhase, UnitType, UnitState
from magi.webui_backend.adapter import MockMagiAdapter, MagiAdapter
from magi.webui_backend.broadcaster import EventBroadcaster

class TestSessionManager(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_injection(self):
        """Verify that SessionManager accepts adapter_factory and broadcaster"""
        broadcaster = EventBroadcaster()
        
        # Mock adapter factory
        adapter_factory = MagicMock(return_value=MockMagiAdapter())
        
        # This will fail before modification because __init__ doesn't accept these args
        manager = SessionManager(
            max_concurrency=5, 
            ttl_sec=60, 
            adapter_factory=adapter_factory,
            broadcaster=broadcaster
        )
        
        self.assertEqual(manager.adapter_factory, adapter_factory)
        self.assertEqual(manager.broadcaster, broadcaster)

    async def test_run_session_integration(self):
        """Verify that _run_session_task uses the adapter and updates session state"""
        broadcaster = EventBroadcaster()
        adapter_factory = MagicMock(return_value=MockMagiAdapter())
        
        manager = SessionManager(
            max_concurrency=5, 
            adapter_factory=adapter_factory,
            broadcaster=broadcaster
        )
        
        # Create session
        session_id = await manager.create_session("test prompt", SessionOptions(max_rounds=1))
        
        # Subscribe immediately
        queue = await broadcaster.subscribe(session_id)
        
        # Wait for completion (MockMagiAdapter runs relatively fast but has sleeps)
        # We can poll the session state
        session = manager.get_session(session_id)
        
        # Wait for RESOLVED or ERROR
        for _ in range(50): # 5 seconds max
            if session.phase in [SessionPhase.RESOLVED, SessionPhase.ERROR]:
                break
            await asyncio.sleep(0.1)
            
        self.assertEqual(session.phase, SessionPhase.RESOLVED)
        self.assertEqual(session.progress, 100)
        
        # Check if events were broadcasted
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
            
        # We might miss the very first events due to race, but we should catch the later ones
        # especially since MockMagiAdapter has sleeps.
        self.assertTrue(len(events) > 0)
        types = [e["type"] for e in events]
        
        # We should definitely see 'final' as it comes at the end
        self.assertIn("final", types)
        
        # Check specific event content
        final_event = next(e for e in events if e["type"] == "final")
        self.assertEqual(final_event["decision"], "APPROVE")

