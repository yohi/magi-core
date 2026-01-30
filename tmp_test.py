import asyncio
from magi.webui_backend.session_manager import SessionManager
from magi.webui_backend.models import SessionPhase

async def main():
    sm = SessionManager()
    print("Creating session...")
    session_id = await sm.create_session("test prompt")
    print(f"Session created: {session_id}")
    
    session = sm.get_session(session_id)
    print(f"Initial phase: {session.phase}")
    
    # Wait for task to start and update state
    await asyncio.sleep(1)
    print(f"Phase after 1s: {session.phase}")
    print(f"Progress: {session.progress}")
    
    # Cancel
    print("Cancelling...")
    await sm.cancel_session(session_id)
    print(f"Phase after cancel: {session.phase}")
    
    # Verify cleanup
    # (Not testing TTL here as it takes too long, but manual check)

if __name__ == "__main__":
    asyncio.run(main())
