import os
import unittest
from fastapi.testclient import TestClient

# Mock mode off
os.environ["MAGI_USE_MOCK"] = "0"
os.environ["MAGI_ANTHROPIC_API_KEY"] = "test-key" # Avoid missing key error

from magi.webui_backend.app import app, session_manager
from magi.webui_backend.adapter import ConsensusEngineMagiAdapter

class TestWebUIProductionMode(unittest.TestCase):
    def test_adapter_type_in_production(self):
        """プロダクションモードでConsensusEngineMagiAdapterが使用されることを確認"""
        adapter = session_manager.adapter_factory()
        self.assertIsInstance(adapter, ConsensusEngineMagiAdapter)

    def test_health_check_production(self):
        """ヘルスチェックがproductionモードを返すことを確認"""
        with TestClient(app) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["mode"], "production")

if __name__ == "__main__":
    unittest.main()
