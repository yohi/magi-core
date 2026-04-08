"""
WebUI WebSocketエンドポイントの単体テスト
"""
import unittest
from unittest.mock import MagicMock, patch
import importlib
from typing import Dict, Any

from fastapi.testclient import TestClient

class TestWebUIWebSocket(unittest.IsolatedAsyncioTestCase):
    """WebSocket接続とメッセージ受信のテスト"""

    async def asyncSetUp(self):
        """テスト前の準備: モックモードを強制し、モジュールをリロード"""
        # MAGI_USE_MOCK=1 を設定して認証エラーを防ぐ
        self.env_patcher = patch.dict("os.environ", {"MAGI_USE_MOCK": "1"})
        self.env_patcher.start()
        
        import magi.webui_backend.adapter
        import magi.webui_backend.app
        # モジュールのリロードにより、use_mock=True な状態の app/session_manager を得る
        importlib.reload(magi.webui_backend.adapter)
        importlib.reload(magi.webui_backend.app)
        
        from magi.webui_backend.app import app, session_manager
        self.app = app
        self.session_manager = session_manager
        self.client = TestClient(self.app)
        
        # 既存のセッションをクリア
        self.session_manager.sessions.clear()

    async def asyncTearDown(self):
        """テスト後の後始末"""
        self.env_patcher.stop()
        
        import magi.webui_backend.adapter
        import magi.webui_backend.app
        importlib.reload(magi.webui_backend.adapter)
        importlib.reload(magi.webui_backend.app)

    def test_ws_connect_success_and_receive_events(self):
        """正常なセッションIDでWS接続し、イベントを受信できることの確認"""
        
        with TestClient(self.app) as client:
            # 1. セッション作成
            create_payload = {
                "prompt": "Test WebSocket",
                "options": {
                    "max_rounds": 1
                }
            }
            resp = client.post("/api/sessions", json=create_payload)
            self.assertEqual(resp.status_code, 201)
            data = resp.json()
            session_id = data["session_id"]
            ws_url = f"/ws/sessions/{session_id}"

            # 2. WebSocket接続
            with client.websocket_connect(ws_url) as websocket:
                received_events = []
                try:
                    # 数回受信を試みる
                    for i in range(10):
                        event = websocket.receive_json()
                        received_events.append(event)
                        
                        self._verify_common_fields(event, session_id)
                        
                        if event.get("type") == "final":
                            break
                except Exception:
                    pass
                
                self.assertGreater(len(received_events), 0, "一つもWebSocketイベントを受信できませんでした")

    def test_ws_connect_invalid_session(self):
        """存在しないセッションIDへの接続が拒否されることの確認"""
        invalid_session_id = "non-existent-session-id"
        ws_url = f"/ws/sessions/{invalid_session_id}"

        with self.assertRaises(Exception):
            with self.client.websocket_connect(ws_url) as websocket:
                websocket.receive_json()

    def test_ws_error_event_has_code(self):
        """例外発生時にエラーイベントに 'code' フィールドが含まれることの確認"""
        with TestClient(self.app) as client:
            create_payload = {
                "prompt": "Test Error Code",
                "options": {"max_rounds": 1}
            }
            
            # モックアダプターの差し替え
            # すでに MockMagiAdapter が使われる設定になっているはずだが、
            # エラーを投げるようにさらに細工する
            mock_adapter = MagicMock()
            
            async def mock_run(*args, **kwargs):
                import asyncio
                await asyncio.sleep(0.1)
                raise ValueError("Simulated Internal Error")
                yield
            
            mock_adapter.run.side_effect = mock_run
            
            # session_manager.adapter_factory を一時的に差し替え
            with patch.object(self.session_manager, 'adapter_factory', return_value=mock_adapter):
                resp = client.post("/api/sessions", json=create_payload)
                self.assertEqual(resp.status_code, 201)
                session_id = resp.json()["session_id"]
                ws_url = f"/ws/sessions/{session_id}"
                
                with client.websocket_connect(ws_url) as websocket:
                    error_event = None
                    for _ in range(10):
                        event = websocket.receive_json()
                        if event.get("type") == "error":
                            error_event = event
                            break
                    
                    if error_event is None:
                        self.fail("エラーイベントを受信できませんでした")
                    
                    self.assertIn("code", error_event)
                    self.assertEqual(error_event["code"], "INTERNAL")

    def _verify_common_fields(self, event: Dict[str, Any], expected_session_id: str):
        """EventBroadcasterが付与する共通フィールドの検証"""
        self.assertIn("schema_version", event)
        self.assertEqual(event["schema_version"], "1.0")
        self.assertIn("session_id", event)
        self.assertEqual(event["session_id"], expected_session_id)
        self.assertIn("ts", event)
        self.assertIsInstance(event["ts"], str)

if __name__ == "__main__":
    unittest.main()
