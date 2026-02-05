
import unittest
from typing import Any, Dict
from magi.core.providers import ProviderAdapterFactory
from magi.llm.auth import AuthContext

class TestProviderAdapterFactory(unittest.TestCase):
    def test_build_auth_context_with_extras(self):
        factory = ProviderAdapterFactory()
        options = {
            "client_id": "test_id",
            "extras": {
                "chatgpt_account_id": "acc_123",
                "custom_param": "value"
            }
        }
        auth_context = factory._build_auth_context(options)
        
        self.assertEqual(auth_context.client_id, "test_id")
        self.assertEqual(auth_context.extras, {
            "chatgpt_account_id": "acc_123",
            "custom_param": "value"
        })

    def test_build_auth_context_without_extras(self):
        factory = ProviderAdapterFactory()
        options = {
            "client_id": "test_id"
        }
        auth_context = factory._build_auth_context(options)
        
        self.assertEqual(auth_context.client_id, "test_id")
        self.assertEqual(auth_context.extras, {})

    def test_build_auth_context_with_none_extras(self):
        factory = ProviderAdapterFactory()
        options = {
            "client_id": "test_id",
            "extras": None
        }
        auth_context = factory._build_auth_context(options)
        
        self.assertEqual(auth_context.client_id, "test_id")
        self.assertEqual(auth_context.extras, {})

if __name__ == "__main__":
    unittest.main()
