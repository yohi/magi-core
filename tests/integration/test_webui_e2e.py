"""
WebUI Backend End-to-End Integration Tests

Requirements:
    - 3.1: API endpoint verification
    - 3.2: WebSocket event streaming
    - 4.1: Integration with ConsensusEngine
"""

import asyncio
import os
import unittest
import logging
import threading
import time
from unittest.mock import patch
from fastapi.testclient import TestClient

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 環境変数を事前設定して ConfigManager が成功するようにする
# これにより MockMagiAdapter ではなく ConsensusEngineMagiAdapter が選択される
os.environ["MAGI_API_KEY"] = "test-api-key"
# os.environ["MAGI_USE_MOCK"] = "0"
os.environ["MAGI_USE_MOCK"] = (
    "1"  # Default to Mock for stable CI/E2E testing without external dependencies
)

# appのインポート (環境変数設定後に行う)
from magi.webui_backend.app import app, session_manager


class TestWebUIEndToEnd(unittest.TestCase):
    def test_session_execution_flow(self):
        """
        ControlledMagiAdapter経由でセッションを作成し、WebSocketで実行結果を受け取るE2Eテスト
        """
        start_event = threading.Event()

        class ControlledMagiAdapter:
            async def run(self, prompt, options):
                while not start_event.is_set():
                    await asyncio.sleep(0.01)

                yield {"type": "phase", "phase": "THINKING"}
                yield {
                    "type": "unit",
                    "unit": "MELCHIOR-1",
                    "state": "THINKING",
                    "message": "MELCHIOR is thinking",
                    "score": 0.0,
                }
                yield {"type": "phase", "phase": "DEBATE"}
                yield {"type": "phase", "phase": "VOTING"}
                yield {
                    "type": "final",
                    "decision": "APPROVE",
                    "votes": {"MELCHIOR-1": {"vote": "YES", "reason": "Test approval"}},
                    "summary": "Test completed",
                }

        with patch.object(
            session_manager, "adapter_factory", return_value=ControlledMagiAdapter()
        ):
            with TestClient(app) as client:
                # 1. セッション作成 (POST /api/sessions)
                response = client.post(
                    "/api/sessions",
                    json={
                        "prompt": "Test Prompt for E2E",
                        "options": {"max_rounds": 1},
                    },
                )
                self.assertEqual(response.status_code, 201)
                data = response.json()

                self.assertIn("session_id", data)
                self.assertIn("ws_url", data)
                ws_url = data["ws_url"]

                # 2. WebSocket接続とイベント受信
                # TestClient.websocket_connect はコンテキストマネージャとして接続を管理
                with client.websocket_connect(ws_url) as websocket:
                    start_event.set()
                    received_events = []

                    # イベントループ
                    start_time = time.monotonic()
                    MAX_WAIT_SECONDS = 5
                    error_event = None
                    
                    while True:
                        if time.monotonic() - start_time > MAX_WAIT_SECONDS:
                            self.fail(
                                f"Timeout ({MAX_WAIT_SECONDS}s) waiting for session completion"
                            )

                        try:
                            data = websocket.receive_json()
                            received_events.append(data)
                        except Exception as e:
                            print(f"WS Exception: {e}")
                            break

                        event_type = data.get("type")

                        # 終了条件
                        if event_type == "final":
                            break
                        if event_type == "error":
                            error_event = data
                            break

                    if error_event is not None:
                        self.fail(f"Received error event: {error_event}")

                    # 3. 検証
                    event_types = [e.get("type") for e in received_events]

                    # 必須イベントが含まれているか
                    self.assertIn("phase", event_types)
                    self.assertIn(
                        "unit", event_types
                    )  # Thinking/Debate/Votingのいずれかでunitイベントが出るはず
                    self.assertIn("final", event_types)

                    # Phase遷移の確認 (順序は保証されないが、出現を確認)
                    phases = [
                        e.get("phase")
                        for e in received_events
                        if e.get("type") == "phase"
                    ]
                    self.assertIn("THINKING", phases)
                    self.assertIn("DEBATE", phases)
                    self.assertIn("VOTING", phases)

                    # 最終結果の検証
                    final_event = next(
                        e for e in received_events if e.get("type") == "final"
                    )
                    self.assertEqual(final_event["decision"], "APPROVE")

                    # 投票結果が含まれているか
                    votes = final_event.get("votes", {})
                    self.assertTrue(len(votes) > 0, "Voting results should be present")

    def test_session_cancel_flow(self):
        """
        セッションをキャンセルし、CANCELLEDフェーズを受け取るE2Eテスト
        """
        start_event = threading.Event()

        class HangingMagiAdapter:
            async def run(self, prompt, options):
                while not start_event.is_set():
                    await asyncio.sleep(0.01)

                yield {"type": "phase", "phase": "THINKING"}

                while True:
                    await asyncio.sleep(1)

        with patch.object(
            session_manager, "adapter_factory", return_value=HangingMagiAdapter()
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/sessions",
                    json={
                        "prompt": "Test Prompt for E2E Cancel",
                        "options": {"max_rounds": 1},
                    },
                )
                self.assertEqual(response.status_code, 201)
                data = response.json()

                session_id = data["session_id"]
                ws_url = data["ws_url"]

                with client.websocket_connect(ws_url) as websocket:
                    start_event.set()
                    _ = websocket.receive_json()

                    cancel_response = client.post(f"/api/sessions/{session_id}/cancel")
                    self.assertEqual(cancel_response.status_code, 200)
                    self.assertEqual(cancel_response.json(), {"status": "cancelled"})

                    cancelled_received = False
                    start_time = time.monotonic()
                    MAX_WAIT_SECONDS = 5

                    while True:
                        if time.monotonic() - start_time > MAX_WAIT_SECONDS:
                            self.fail(
                                f"Timeout ({MAX_WAIT_SECONDS}s) waiting for CANCELLED phase"
                            )

                        try:
                            event = websocket.receive_json()
                        except Exception:
                            break

                        event_type = event.get("type")
                        if event_type == "error":
                            self.fail(
                                f"Received error event during cancel flow: {event}"
                            )

                        if event_type == "phase" and event.get("phase") == "CANCELLED":
                            cancelled_received = True
                            break

                        if event_type == "final":
                            break

                    self.assertTrue(
                        cancelled_received, "CANCELLEDフェーズが受信されていません"
                    )

    def test_session_error_flow(self):
        """
        エラーイベントが配信されることを確認するE2Eテスト
        """
        start_event = threading.Event()

        class ErrorMagiAdapter:
            async def run(self, prompt, options):
                while not start_event.is_set():
                    await asyncio.sleep(0.01)

                yield {
                    "type": "error",
                    "code": "E2E_TEST_ERROR",
                    "message": "E2E error simulation",
                }

        with patch.object(
            session_manager, "adapter_factory", return_value=ErrorMagiAdapter()
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/sessions",
                    json={
                        "prompt": "Test Prompt for E2E Error",
                        "options": {"max_rounds": 1},
                    },
                )
                self.assertEqual(response.status_code, 201)
                data = response.json()

                ws_url = data["ws_url"]

                with client.websocket_connect(ws_url) as websocket:
                    start_event.set()
                    start_time = time.monotonic()
                    MAX_WAIT_SECONDS = 5

                    event = None
                    while True:
                        if time.monotonic() - start_time > MAX_WAIT_SECONDS:
                            self.fail(
                                f"Timeout ({MAX_WAIT_SECONDS}s) waiting for error event"
                            )

                        try:
                            event = websocket.receive_json()
                            break
                        except Exception:
                            break

                    if event is None:
                        self.fail("Error event was not received")
                    self.assertEqual(event.get("type"), "error")
                    self.assertEqual(event.get("code"), "E2E_TEST_ERROR")
                    self.assertEqual(event.get("message"), "E2E error simulation")

    def test_health_check(self):
        """ヘルスチェックエンドポイントのテスト"""
        with TestClient(app) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
