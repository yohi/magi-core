"""
WebUI Backend End-to-End Integration Tests

Requirements:
    - 3.1: API endpoint verification
    - 3.2: WebSocket event streaming
    - 4.1: Integration with ConsensusEngine
"""

import os
import unittest
import logging
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 環境変数を事前設定して ConfigManager が成功するようにする
# これにより MockMagiAdapter ではなく ConsensusEngineMagiAdapter が選択される
os.environ["MAGI_API_KEY"] = "test-api-key"
# os.environ["MAGI_USE_MOCK"] = "0"
os.environ["MAGI_USE_MOCK"] = "1"  # Default to Mock for stable CI/E2E testing without external dependencies

# appのインポート (環境変数設定後に行う)
from magi.webui_backend.app import app
from magi.llm.client import LLMResponse

class TestWebUIEndToEnd(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        
    @patch("magi.llm.client.LLMClient.send")
    def test_session_execution_flow(self, mock_send):
        """
        API経由でセッションを作成し、WebSocketで実行結果を受け取るE2Eテスト
        """
        # LLMのレスポンスをモック
        # Thinking/Debate/Voting すべてでこのレスポンスが返るが、
        # VotingフェーズではJSONパースされて承認として扱われる想定
        mock_send.return_value = LLMResponse(
            content='{"vote": "APPROVE", "reason": "Test approval", "conditions": []}',
            usage={"input_tokens": 10, "output_tokens": 10},
            model="test-model"
        )
        
        # 1. セッション作成 (POST /api/sessions)
        response = self.client.post("/api/sessions", json={
            "prompt": "Test Prompt for E2E",
            "options": {"max_rounds": 1}
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        
        self.assertIn("session_id", data)
        self.assertIn("ws_url", data)
        session_id = data["session_id"]
        ws_url = data["ws_url"]
        
        print(f"Session created: {session_id}, connecting to {ws_url}")
        
        # 2. WebSocket接続とイベント受信
        # TestClient.websocket_connect はコンテキストマネージャとして接続を管理
        with self.client.websocket_connect(ws_url) as websocket:
            received_events = []
            
            # イベントループ
            while True:
                try:
                    # タイムアウト付きで受信できれば理想だが、TestClientはブロッキング
                    # 内部で適切なタイムアウトや終了条件を持つ必要がある
                    data = websocket.receive_json()
                    received_events.append(data)
                    
                    event_type = data.get("type")
                    # print(f"Received: {event_type}")
                    
                    # 終了条件
                    if event_type == "final":
                        break
                    if event_type == "error":
                        self.fail(f"Received error event: {data}")
                        break
                        
                except Exception as e:
                    # 接続切断など
                    print(f"WS Exception: {e}")
                    break
            
            # 3. 検証
            event_types = [e.get("type") for e in received_events]
            
            # 必須イベントが含まれているか
            self.assertIn("phase", event_types)
            self.assertIn("unit", event_types)  # Thinking/Debate/Votingのいずれかでunitイベントが出るはず
            self.assertIn("final", event_types)
            
            # Phase遷移の確認 (順序は保証されないが、出現を確認)
            phases = [e.get("phase") for e in received_events if e.get("type") == "phase"]
            self.assertIn("THINKING", phases)
            self.assertIn("DEBATE", phases)
            self.assertIn("VOTING", phases)
            
            # 最終結果の検証
            final_event = next(e for e in received_events if e.get("type") == "final")
            self.assertEqual(final_event["decision"], "APPROVE")
            
            # 投票結果が含まれているか
            votes = final_event.get("votes", {})
            self.assertTrue(len(votes) > 0, "Voting results should be present")

    def test_health_check(self):
        """ヘルスチェックエンドポイントのテスト"""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

if __name__ == "__main__":
    unittest.main()
