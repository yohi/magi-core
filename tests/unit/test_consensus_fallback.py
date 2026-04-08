"""
ConsensusEngine のフォールバックに関するユニットテスト

ProviderSelector によるプロバイダ解決が失敗した際に、
レガシーな LLMClient へ適切にフォールバックされることを検証します。
"""
import unittest
from unittest.mock import MagicMock, patch
from magi.core.consensus import ConsensusEngine
from magi.config.manager import Config
from magi.config.settings import PersonaConfig, LLMConfig
from magi.llm.client import LLMClient
from magi.models import PersonaType

class TestConsensusFallback(unittest.TestCase):
    """ConsensusEngine のフォールバックロジックを検証するテストクラス"""
    def test_consensus_engine_fallback_to_legacy_llm_client(self):
        """ProviderSelector が失敗した場合にレガシー LLMClient にフォールバックすることを確認"""
        config = Config()
        config.api_key = "legacy-key"
        config.model = "legacy-model"
        
        # personas を初期化
        config.personas = {
            "melchior": PersonaConfig(llm=LLMConfig(model="anthropic/claude-3"))
        }
        
        # ProviderSelector のモック。select() が期待通りの例外を投げるように設定
        mock_selector = MagicMock()
        mock_selector.select.side_effect = RuntimeError("Selector failure")
        
        engine = ConsensusEngine(
            config=config,
            provider_selector=mock_selector
        )
        
        # _resolve_llm_client を呼び出す (内部で selector.select を呼ぶ)
        client = engine._resolve_llm_client(PersonaType.MELCHIOR)
        
        # LLMClient (レガシー) が返されていることを確認
        self.assertIsInstance(client, LLMClient)
        self.assertEqual(client.api_key, "legacy-key")
        self.assertEqual(client.model, "anthropic/claude-3") # llm_config.model が優先される

if __name__ == "__main__":
    unittest.main()
