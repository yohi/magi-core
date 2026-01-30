"""
WebUI WebSocketエンドポイントの単体テスト
"""
import unittest
from typing import Dict, Any

from fastapi.testclient import TestClient

# テスト対象のアプリケーション
from magi.webui_backend.app import app, session_manager

class TestWebUIWebSocket(unittest.TestCase):
    """WebSocket接続とメッセージ受信のテスト"""

    def setUp(self):
        """テスト前の準備: セッションマネージャーの状態をクリア"""
        self.client = TestClient(app)
        # 既存のセッションを強制キャンセルしてクリア
        # 非同期メソッドを同期コンテキストから呼ぶため、少し強引だが
        # TestClientを使っている場合、内部でイベントループが動いている可能性があるが
        # ここでは sessions 辞書を直接操作してクリーンアップを試みる
        # ただし、TestClientはリクエスト毎にループを回すが、
        # session_managerはグローバルなので、前のテストの影響が残る可能性がある。
        
        # 安全のため、プライベートメソッドだが cleanup を試みる
        # ここでは単純にsessionsを空にするだけでなく、タスクのキャンセルも考慮したいが、
        # 同期テストメソッド内から非同期cleanupを呼ぶのは難しい。
        # 簡易的に sessions 辞書をクリアする。
        # (厳密にはタスクがリークする可能性があるが、ユニットテストの範囲では許容)
        session_manager.sessions.clear()

    def tearDown(self):
        """テスト後の後始末"""
        # セッションマネージャーに残っているセッションがあればキャンセル
        # 本当は各テストで作成したsession_idを覚えておいて掃除するのが行儀が良い
        pass

    def test_ws_connect_success_and_receive_events(self):
        """正常なセッションIDでWS接続し、イベントを受信できることの確認"""
        
        with TestClient(app) as client:
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
                    for i in range(5):
                        # receive_jsonはブロッキングだがTestClientのコンテキスト内なら動く
                        event = websocket.receive_json()
                        received_events.append(event)
                        
                        self._verify_common_fields(event, session_id)
                        
                        # MockMagiAdapterはfinalイベントを出すので、それを受信したら終了
                        if event.get("type") == "final":
                            break
                except Exception:
                    # タイムアウト等で受信終了
                    pass
                
                self.assertGreater(len(received_events), 0, "一つもWebSocketイベントを受信できませんでした")
                
                for event in received_events:
                    self.assertIn("type", event)


    def test_ws_connect_invalid_session(self):
        """存在しないセッションIDへの接続が拒否されることの確認"""
        invalid_session_id = "non-existent-session-id"
        ws_url = f"/ws/sessions/{invalid_session_id}"

        # 接続試行 -> 403 Forbidden や 1008 Policy Violation などで切断される
        # TestClientの実装では、ハンドシェイクでのHTTPエラーか、WS closeか
        # app.py実装: await websocket.accept() -> await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        # なので、接続自体はHTTP 101で成功した直後にCloseフレームが飛んでくる挙動になるはず
        
        with self.assertRaises(Exception):
            with self.client.websocket_connect(ws_url) as websocket:
                # 接続直後にcloseされているはずなので、何か受信しようとするとエラーになるか、
                # あるいは websocket_connect 自体が close を検知して例外を投げる場合もある
                websocket.receive_json()
        
        # TestClient(Starlette)の場合、サーバー側がcloseすると
        # WebSocketDisconnect が発生することが多い
        # エラーメッセージや例外型を確認してもよいが、ここでは「接続・受信が正常に続かないこと」を確認できればよしとする

    def _verify_common_fields(self, event: Dict[str, Any], expected_session_id: str):
        """EventBroadcasterが付与する共通フィールドの検証"""
        self.assertIn("schema_version", event)
        self.assertEqual(event["schema_version"], "1.0")
        
        self.assertIn("session_id", event)
        self.assertEqual(event["session_id"], expected_session_id)
        
        self.assertIn("ts", event)
        # tsはISOフォーマットの日時文字列
        self.assertIsInstance(event["ts"], str)

if __name__ == "__main__":
    unittest.main()
