"""
スキーマ検証ユーティリティ

投票ペイロードやテンプレートメタデータの簡易検証を行う。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from magi.models import Vote


@dataclass
class ValidationResult:
    """スキーマ検証結果"""

    ok: bool
    errors: List[str]


class SchemaValidationError(Exception):
    """スキーマ検証失敗を表す例外"""

    def __init__(self, errors: List[str]):
        self.errors = errors
        message = "; ".join(errors)
        super().__init__(message)


class SchemaValidator:
    """JSON Schema 互換の簡易検証器

    jsonschema に依存せず必須フィールドと型のみをチェックする。
    """

    _ALLOWED_VOTES = {
        Vote.APPROVE.value.upper(),
        Vote.DENY.value.upper(),
        Vote.CONDITIONAL.value.upper(),
    }

    def __init__(self, template_required_fields: Optional[List[str]] = None):
        self._template_required_fields = template_required_fields or [
            "name",
            "version",
            "schema_ref",
            "template",
        ]

    def validate_vote_payload(self, payload: Dict[str, Any]) -> ValidationResult:
        """投票ペイロードを検証する"""
        errors: List[str] = []

        if not isinstance(payload, dict):
            return ValidationResult(False, ["payload はオブジェクトである必要があります"])

        vote_value = payload.get("vote")
        if isinstance(vote_value, str):
            vote_normalized = vote_value.strip().upper()
        else:
            vote_normalized = str(vote_value).upper() if vote_value is not None else ""

        if vote_normalized not in self._ALLOWED_VOTES:
            errors.append("vote は APPROVE | DENY | CONDITIONAL のいずれかを指定してください")

        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append("reason は非空文字列である必要があります")

        if "conditions" in payload:
            conditions = payload.get("conditions")
            if not isinstance(conditions, list) or any(
                not isinstance(item, str) for item in conditions
            ):
                errors.append("conditions は文字列リストである必要があります")

        return ValidationResult(ok=len(errors) == 0, errors=errors)

    def validate_template_meta(self, meta: Dict[str, Any]) -> ValidationResult:
        """テンプレートメタデータを検証する"""
        errors: List[str] = []

        if not isinstance(meta, dict):
            return ValidationResult(False, ["テンプレートメタデータはオブジェクトである必要があります"])

        for field_name in self._template_required_fields:
            value = meta.get(field_name)
            if value is None:
                errors.append(f"{field_name} が不足しています")
            elif not isinstance(value, str) or not value.strip():
                errors.append(f"{field_name} は非空文字列である必要があります")

        if "variables" in meta and not isinstance(meta["variables"], dict):
            errors.append("variables はオブジェクトである必要があります")

        return ValidationResult(ok=len(errors) == 0, errors=errors)
