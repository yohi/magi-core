
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
        self.assertIsNotNone(session)
        if session is None: return
        
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

    async def test_session_timeout(self):
        """Verify that a slow adapter triggers a timeout"""
        broadcaster = EventBroadcaster()
        
        class SlowAdapter(MockMagiAdapter):
            async def run(self, prompt, options):
                yield {"type": "log", "lines": ["Starting..."]}
                await asyncio.sleep(2.0)
                yield {"type": "final", "decision": "APPROVE"}
                
        adapter_factory = MagicMock(return_value=SlowAdapter())
        manager = SessionManager(
            max_concurrency=5, 
            adapter_factory=adapter_factory,
            broadcaster=broadcaster
        )
        
        options = SessionOptions(timeout_sec=0.1)
        session_id = await manager.create_session("test prompt", options)
        
        queue = await broadcaster.subscribe(session_id)
        session = manager.get_session(session_id)
        self.assertIsNotNone(session)
        if session is None: return
        
        for _ in range(20):
            if session.phase == SessionPhase.ERROR:
                break
            await asyncio.sleep(0.1)
            
        self.assertEqual(session.phase, SessionPhase.ERROR)
        
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
            
        self.assertTrue(any(e.get("type") == "error" and e.get("code") == "TIMEOUT" for e in events))

    async def test_periodic_cleanup(self):
        """Verify that expired sessions are removed automatically by the background task"""
        manager = SessionManager(
            max_concurrency=5,
            ttl_sec=1,
        )
        
        manager.start_cleanup_task(interval_sec=0.1)
        
        try:
            session_id = await manager.create_session("test prompt")
            session = manager.get_session(session_id)
            self.assertIsNotNone(session)
            
            await asyncio.sleep(1.5)
            
            self.assertIsNone(manager.get_session(session_id))
            self.assertNotIn(session_id, manager.sessions)
            
        finally:
            await manager.stop_cleanup_task()

