"""
スキーマ検証ユーティリティ

投票ペイロードやテンプレートメタデータの簡易検証を行う。
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from jsonschema import Draft7Validator, exceptions as jsonschema_exceptions

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
    """JSON Schema 互換の検証器

    jsonschema を用いて必須項目・型・値域を検証し、互換性のための軽微な
    追加チェック（大文字正規化など）も行う。
    """

    _ALLOWED_VOTES = {
        Vote.APPROVE.value.upper(),
        Vote.DENY.value.upper(),
        Vote.CONDITIONAL.value.upper(),
    }

    _DEFAULT_VOTE_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "required": ["vote", "reason"],
        "properties": {
            "vote": {
                "type": "string",
                "minLength": 1,
            },
            "reason": {"type": "string", "minLength": 1},
            "conditions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "additionalProperties": True,
    }

    def __init__(
        self,
        template_required_fields: Optional[List[str]] = None,
        vote_schema: Optional[Dict[str, Any]] = None,
    ):
        self._template_required_fields = template_required_fields or [
            "name",
            "version",
            "schema_ref",
            "template",
        ]
        self._vote_schema = deepcopy(vote_schema or self._DEFAULT_VOTE_SCHEMA)
        self._vote_validator = Draft7Validator(self._vote_schema)

    @staticmethod
    def _format_error(error: jsonschema_exceptions.ValidationError) -> str:
        """jsonschema のエラーをプレーン文字列に整形する"""
        path = "$"
        for elem in error.absolute_path:
            if isinstance(elem, int):
                path += f"[{elem}]"
            else:
                path += f".{elem}"
        return f"{path}: {error.message}"

    @staticmethod
    def _normalize_vote_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """検証前に軽微な正規化を行う"""
        normalized = dict(payload)
        vote_value = normalized.get("vote")
        if isinstance(vote_value, str):
            normalized["vote"] = vote_value.strip()
        reason_value = normalized.get("reason")
        if isinstance(reason_value, str):
            normalized["reason"] = reason_value.strip()
        return normalized

    def validate_vote_payload(self, payload: Dict[str, Any]) -> ValidationResult:
        """投票ペイロードを検証する"""
        errors: List[str] = []

        if not isinstance(payload, dict):
            return ValidationResult(False, ["payload はオブジェクトである必要があります"])

        normalized_payload = self._normalize_vote_payload(payload)
        schema_errors = sorted(
            self._vote_validator.iter_errors(normalized_payload),
            key=lambda err: list(err.absolute_path),
        )
        for error in schema_errors:
            errors.append(self._format_error(error))

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
                not isinstance(item, str) or not item.strip()
                for item in conditions
            ):
                errors.append("conditions は空でない文字列リストである必要があります")

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
