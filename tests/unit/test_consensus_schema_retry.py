"""ConsensusEngine のスキーマリトライ挙動を検証する"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from magi.config.manager import Config
from magi.core.consensus import ConsensusEngine
from magi.core.schema_validator import SchemaValidationError, SchemaValidator
from magi.core.template_loader import TemplateLoader
from magi.models import PersonaType, Vote, VoteOutput


class TestConsensusSchemaRetry(unittest.TestCase):
    """Voting フェーズのスキーマリトライをテストする"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        # 投票テンプレートを配置
        (base / "vote_prompt.yaml").write_text(
            "name: vote_prompt\nversion: v1\nschema_ref: vote_schema.json\n"
            "template: \"{context}\"\n",
            encoding="utf-8",
        )
        self.validator = SchemaValidator()
        self.template_loader = TemplateLoader(
            base, schema_validator=self.validator
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_retry_then_success(self):
        """スキーマ検証失敗後にリトライ成功する"""
        config = Config(
            api_key="test",
            schema_retry_count=1,
            template_base_path=self.temp_dir.name,
        )
        engine = ConsensusEngine(
            config, schema_validator=self.validator, template_loader=self.template_loader
        )

        valid_vote = VoteOutput(
            persona_type=PersonaType.MELCHIOR,
            vote=Vote.APPROVE,
            reason="ok",
        )
        agent = MagicMock()
        agent.vote = AsyncMock(
            side_effect=[SchemaValidationError(["missing reason"]), valid_vote]
        )

        with patch.object(
            engine, "_create_agents", return_value={PersonaType.MELCHIOR: agent}
        ), patch.object(engine, "_build_voting_context", return_value="ctx"):
            result = asyncio.run(engine._run_voting_phase({}, []))

        self.assertIn(PersonaType.MELCHIOR, result["voting_results"])
        self.assertEqual(result["voting_results"][PersonaType.MELCHIOR].vote, Vote.APPROVE)
        self.assertEqual(result["exit_code"], 0)

    def test_retry_exhaustion_records_error(self):
        """再試行上限到達でエラーが記録される"""
        config = Config(
            api_key="test",
            schema_retry_count=0,
            template_base_path=self.temp_dir.name,
        )
        engine = ConsensusEngine(
            config, schema_validator=self.validator, template_loader=self.template_loader
        )

        agent = MagicMock()
        agent.vote = AsyncMock(side_effect=[SchemaValidationError(["invalid schema"])])

        with patch.object(
            engine, "_create_agents", return_value={PersonaType.MELCHIOR: agent}
        ), patch.object(engine, "_build_voting_context", return_value="ctx"):
            result = asyncio.run(engine._run_voting_phase({}, []))

        self.assertEqual(result["voting_results"], {})
        self.assertGreaterEqual(len(engine.errors), 1)
        self.assertEqual(
            engine.errors[0]["code"], "CONSENSUS_SCHEMA_RETRY_EXCEEDED"
        )


if __name__ == "__main__":
    unittest.main()
