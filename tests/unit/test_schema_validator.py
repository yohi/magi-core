"""SchemaValidator のユニットテスト"""

import unittest

from magi.core.schema_validator import SchemaValidationError, SchemaValidator
from magi.models import Vote


class TestSchemaValidator(unittest.TestCase):
    """SchemaValidatorの挙動を検証する"""

    def setUp(self):
        self.validator = SchemaValidator()

    def test_vote_payload_valid(self):
        """有効な投票ペイロードは成功する"""
        payload = {"vote": "APPROVE", "reason": "ok"}
        result = self.validator.validate_vote_payload(payload)
        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])

    def test_vote_payload_invalid_vote(self):
        """無効なvote値はエラーになる"""
        payload = {"vote": "INVALID", "reason": "ng"}
        result = self.validator.validate_vote_payload(payload)
        self.assertFalse(result.ok)
        self.assertIn("vote", result.errors[0])

    def test_vote_payload_invalid_conditions(self):
        """conditions が不正ならエラーを返す"""
        payload = {
            "vote": Vote.CONDITIONAL.value,
            "reason": "need conditions",
            "conditions": ["ok", 123],
        }
        result = self.validator.validate_vote_payload(payload)
        self.assertFalse(result.ok)
        self.assertIn("conditions", result.errors[0])

    def test_vote_payload_requires_dict(self):
        """ペイロードが辞書でない場合はエラーを返す"""
        result = self.validator.validate_vote_payload("not-a-dict")

        self.assertFalse(result.ok)
        self.assertIn("payload はオブジェクトである必要があります", result.errors[0])

    def test_vote_payload_requires_non_empty_reason(self):
        """reason が空白のみならエラー"""
        payload = {"vote": Vote.APPROVE.value, "reason": "   "}

        result = self.validator.validate_vote_payload(payload)

        self.assertFalse(result.ok)
        self.assertIn("reason は非空文字列である必要があります", result.errors[0])

    def test_template_meta_required_fields(self):
        """テンプレートメタの必須フィールドを検証する"""
        meta = {
            "name": "vote_prompt",
            "version": "1.0.0",
            "schema_ref": "schema.json",
            "template": "Hello {context}",
        }
        result = self.validator.validate_template_meta(meta)
        self.assertTrue(result.ok)

    def test_template_meta_missing(self):
        """テンプレートメタの不足フィールドを検知する"""
        meta = {"name": "vote_prompt"}
        result = self.validator.validate_template_meta(meta)
        self.assertFalse(result.ok)
        self.assertGreaterEqual(len(result.errors), 1)

    def test_template_meta_variables_must_be_object(self):
        """variables が辞書以外の場合はエラー"""
        meta = {
            "name": "vote_prompt",
            "version": "1.0.0",
            "schema_ref": "schema.json",
            "template": "Hello {context}",
            "variables": ["not", "dict"],
        }

        result = self.validator.validate_template_meta(meta)

        self.assertFalse(result.ok)
        self.assertIn("variables はオブジェクトである必要があります", result.errors[0])


class TestSchemaValidationError(unittest.TestCase):
    """SchemaValidationError のメッセージ整形を確認する"""

    def test_error_message_join(self):
        """複数エラーがメッセージに含まれる"""
        error = SchemaValidationError(["a", "b"])
        self.assertIn("a", str(error))
        self.assertIn("b", str(error))


if __name__ == "__main__":
    unittest.main()
