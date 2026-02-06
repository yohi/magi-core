"""
WebUI REST APIスペック準拠の単体テスト (TDD Step 1: 失敗するテスト)
"""
import unittest
from fastapi.testclient import TestClient

# テスト対象のアプリケーション
from magi.webui_backend.app import app

class TestWebUIRest(unittest.TestCase):
    """REST APIエンドポイントのスペック準拠テスト"""

    def setUp(self):
        """テスト前の準備"""
        self.client = TestClient(app)

    @unittest.expectedFailure
    def test_create_session_queued_status(self):
        """
        POST /api/sessions
        スペックでは status: "QUEUED" を期待する。
        現在は "created" を返しているため、このテストは失敗するはず。
        """
        payload = {
            "prompt": "Test session for QUEUED status",
            "options": {
                "max_rounds": 1
            }
        }
        response = self.client.post("/api/sessions", json=payload)
        
        # 201 Created は維持しつつ、ステータス文字列を検証
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "QUEUED", f"Expected 'QUEUED', but got '{data['status']}'")

    def test_cancel_session_cancelled_status(self):
        """
        POST /api/sessions/{id}/cancel
        スペックでは status: "CANCELLED" を期待する。
        現在は "cancelled" を返しているため、このテストは失敗するはず。
        """
        # 1. セッション作成
        create_payload = {
            "prompt": "Session to be cancelled",
            "options": {"max_rounds": 1}
        }
        create_resp = self.client.post("/api/sessions", json=create_payload)
        session_id = create_resp.json()["session_id"]

        # 2. キャンセル実行
        cancel_resp = self.client.post(f"/api/sessions/{session_id}/cancel")
        
        self.assertEqual(cancel_resp.status_code, 200)
        data = cancel_resp.json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "CANCELLED", f"Expected 'CANCELLED', but got '{data['status']}'")

    @unittest.expectedFailure
    def test_create_session_validation_empty_prompt(self):
        """
        プロンプトが空の場合、422 Unprocessable Entity (または400) を期待する。
        現在はバリデーションがないため、201で成功してしまい、このテストは失敗するはず。
        """
        payload = {
            "prompt": "",
            "options": {"max_rounds": 1}
        }
        response = self.client.post("/api/sessions", json=payload)
        
        # Pydantic等でのバリデーションエラーを期待
        self.assertIn(response.status_code, [400, 422], f"Expected 400 or 422 for empty prompt, but got {response.status_code}")

    @unittest.expectedFailure
    def test_create_session_validation_too_long_prompt(self):
        """
        プロンプトが長すぎる (>8000文字) 場合、422/400 を期待する。
        現在はバリデーションがないため、201で成功してしまい、このテストは失敗するはず。
        """
        payload = {
            "prompt": "a" * 8001,
            "options": {"max_rounds": 1}
        }
        response = self.client.post("/api/sessions", json=payload)
        
        self.assertIn(response.status_code, [400, 422], f"Expected 400 or 422 for too long prompt, but got {response.status_code}")

if __name__ == "__main__":
    unittest.main()
