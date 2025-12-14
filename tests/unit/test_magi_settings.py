"""
MagiSettings のユニットテスト
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from magi.config.settings import MagiSettings


class TestMagiSettings(unittest.TestCase):
    """MagiSettings の基本動作を検証する"""

    def test_default_values(self):
        """必須項目のみで生成した場合にデフォルト値が適用される"""
        settings = MagiSettings(api_key="test-api-key")

        self.assertEqual(settings.api_key, "test-api-key")
        self.assertEqual(settings.model, "claude-sonnet-4-20250514")
        self.assertEqual(settings.timeout, 60)
        self.assertEqual(settings.retry_count, 3)
        self.assertEqual(settings.debate_rounds, 1)
        self.assertEqual(settings.voting_threshold, "majority")
        self.assertEqual(settings.quorum_threshold, 2)
        self.assertEqual(settings.token_budget, 8192)
        self.assertEqual(settings.schema_retry_count, 3)
        self.assertEqual(settings.template_ttl_seconds, 300)
        self.assertEqual(settings.vote_template_name, "vote_prompt")
        self.assertEqual(settings.template_base_path, "templates")
        self.assertEqual(settings.stream_retry_count, 5)
        self.assertEqual(settings.llm_concurrency_limit, 5)
        self.assertEqual(settings.plugin_concurrency_limit, 3)
        self.assertEqual(settings.plugin_load_timeout, 30.0)
        self.assertFalse(settings.streaming_enabled)
        self.assertEqual(settings.streaming_queue_size, 100)
        self.assertEqual(settings.streaming_overflow_policy, "drop")
        self.assertEqual(settings.streaming_emit_timeout, 2.0)
        self.assertFalse(settings.guardrails_enabled)
        self.assertEqual(settings.guardrails_timeout, 3.0)
        self.assertEqual(settings.guardrails_on_timeout, "fail-closed")
        self.assertEqual(settings.guardrails_on_error, "fail-closed")
        self.assertTrue(settings.log_context_reduction_key)
        self.assertTrue(settings.enable_hardened_consensus)
        self.assertFalse(settings.legacy_fallback_on_fail_safe)
        self.assertEqual(settings.guardrails_providers, {})
        self.assertFalse(settings.plugin_prompt_override_allowed)
        self.assertEqual(settings.plugin_trusted_signatures, [])
        self.assertFalse(settings.production_mode)
        self.assertIsNone(settings.plugin_public_key_path)
        self.assertEqual(settings.output_format, "markdown")

    @patch.dict(
        os.environ,
        {
            "MAGI_API_KEY": "env-api-key",
            "MAGI_MODEL": "env-model",
            "MAGI_STREAMING_OVERFLOW_POLICY": "backpressure",
        },
        clear=True,
    )
    def test_env_prefix_loading(self):
        """環境変数が env_prefix 付きで読み込まれる"""
        settings = MagiSettings()

        self.assertEqual(settings.api_key, "env-api-key")
        self.assertEqual(settings.model, "env-model")
        self.assertEqual(settings.streaming_overflow_policy, "backpressure")

    def test_production_mode_requires_public_key_path(self):
        """production_mode 有効時は公開鍵パスが必須"""
        with self.assertRaises(ValidationError):
            MagiSettings(api_key="test", production_mode=True)

    def test_production_mode_accepts_public_key_path(self):
        """production_mode 有効かつ公開鍵パス指定で通過する"""
        key_path = Path("/tmp/public_key.pem")

        settings = MagiSettings(
            api_key="test",
            production_mode=True,
            plugin_public_key_path=key_path,
        )

        self.assertEqual(settings.plugin_public_key_path, key_path)

    def test_dump_masked_masks_api_key(self):
        """dump_masked で API キーがマスクされる"""
        settings = MagiSettings(api_key="1234567890abcdef")

        masked = settings.dump_masked()

        self.assertEqual(masked["api_key"], "12345678...cdef")
        self.assertEqual(masked["output_format"], "markdown")

    def test_extra_fields_forbidden(self):
        """未知フィールドはバリデーションエラーとなる"""
        with self.assertRaises(ValidationError):
            MagiSettings(api_key="test", unknown_field="value")


if __name__ == "__main__":
    unittest.main()
