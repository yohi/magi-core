import unittest
from unittest.mock import patch
import importlib
import magi.webui_backend.app
import magi.webui_backend.adapter
from fastapi.testclient import TestClient

class TestWebUIProductionMode(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 環境変数をパッチしてモジュールをリロードする
        # これにより、テストごとにフレッシュな設定で実行される
        self.env_patcher = patch.dict("os.environ", {
            "MAGI_USE_MOCK": "0",
            "MAGI_ANTHROPIC_API_KEY": "test-key"
        })
        self.env_patcher.start()
        
        # モジュールのリロード
        importlib.reload(magi.webui_backend.adapter)
        importlib.reload(magi.webui_backend.app)
        
        from magi.webui_backend.app import app, session_manager
        from magi.webui_backend.adapter import ConsensusEngineMagiAdapter
        self.app = app
        self.session_manager = session_manager
        self.ConsensusEngineMagiAdapter = ConsensusEngineMagiAdapter

    async def asyncTearDown(self):
        self.env_patcher.stop()

    def test_adapter_type_in_production(self):
        """プロダクションモードでConsensusEngineMagiAdapterが使用されることを確認"""
        adapter = self.session_manager.adapter_factory()
        self.assertIsInstance(adapter, self.ConsensusEngineMagiAdapter)

    async def test_production_adapter_initial_output(self):
        """プロダクションアダプターが初期フェーズと進捗を正しく出力することを検証"""
        from magi.webui_backend.models import SessionOptions
        adapter = self.session_manager.adapter_factory()
        
        # 実行の最初のイベントを取得
        events = []
        async for event in adapter.run("test", SessionOptions()):
            events.append(event)
            if len(events) >= 2:
                break
        
        # 初期イベントの検証
        self.assertEqual(events[0], {"type": "phase", "phase": "THINKING"})
        self.assertEqual(events[1], {"type": "progress", "pct": 10})

    def test_health_check_production(self):
        """ヘルスチェックがproductionモードを返すことを確認"""
        with TestClient(self.app) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["mode"], "production")

if __name__ == "__main__":
    unittest.main()
