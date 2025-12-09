"""
テンプレートローダー

YAML/JSON/Jinja2 形式のテンプレートを読み込み、TTL 付きキャッシュで管理する。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import json
import logging

import yaml

from magi.core.schema_validator import SchemaValidationError, SchemaValidator

logger = logging.getLogger(__name__)


@dataclass
class TemplateRevision:
    """テンプレートのリビジョン情報"""

    name: str
    version: str
    schema_ref: str
    template: str
    variables: Optional[Dict[str, str]]
    loaded_at: datetime


class TemplateLoader:
    """外部テンプレートの読み込みとキャッシュ管理を行うローダー"""

    def __init__(
        self,
        base_path: Path,
        ttl_seconds: int = 300,
        now_fn: Optional[Callable[[], datetime]] = None,
        schema_validator: Optional[SchemaValidator] = None,
        event_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self._base_path = Path(base_path)
        self._ttl_seconds = ttl_seconds
        self._now = now_fn or datetime.utcnow
        self._validator = schema_validator or SchemaValidator()
        self._cache: Dict[str, TemplateRevision] = {}
        self._event_hook = event_hook

    def load(self, name: str) -> TemplateRevision:
        """テンプレートを読み込む（キャッシュ優先）"""
        cached = self._cache.get(name)
        if cached and not self._is_expired(cached):
            return cached
        return self._reload(name, reason="auto")

    def reload(self, name: str, mode: str = "force") -> TemplateRevision:
        """テンプレートを再読み込みする"""
        reason = "force" if mode == "force" else "ttl"
        return self._reload(name, reason=reason)

    def cached(self, name: str) -> Optional[TemplateRevision]:
        """キャッシュ済みリビジョンを返す"""
        return self._cache.get(name)

    def set_event_hook(self, event_hook: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """イベントフックを動的に設定する"""
        self._event_hook = event_hook

    def _reload(self, name: str, reason: str) -> TemplateRevision:
        path = self._resolve_path(name)
        meta, template_body = self._read_file(path)

        validation = self._validator.validate_template_meta(meta)
        if not validation.ok:
            raise SchemaValidationError(validation.errors)

        revision = TemplateRevision(
            name=meta["name"],
            version=meta["version"],
            schema_ref=meta["schema_ref"],
            template=template_body,
            variables=meta.get("variables"),
            loaded_at=self._now(),
        )

        previous = self._cache.get(name)
        self._cache[name] = revision
        logger.info(
            "consensus.template.reload reason=%s previous=%s new=%s ttl=%s",
            reason,
            previous.version if previous else "none",
            revision.version,
            self._ttl_seconds,
        )
        self._emit_event(
            "template.reload",
            reason=reason,
            previous_version=previous.version if previous else "none",
            new_version=revision.version,
            ttl=self._ttl_seconds,
        )
        if previous and previous.version != revision.version:
            logger.info(
                "consensus.template.version_changed old=%s new=%s mode=%s",
                previous.version,
                revision.version,
                "hot-reload" if reason != "auto" else "auto",
            )
            self._emit_event(
                "template.version_changed",
                old=previous.version,
                new=revision.version,
                mode="hot-reload" if reason != "auto" else "auto",
            )
        return revision

    def _resolve_path(self, name: str) -> Path:
        """テンプレートファイルの解決を行う"""
        # パストラバーサル対策
        if ".." in name or name.startswith("/"):
            raise ValueError(f"不正なテンプレート名です: {name}")

        base_path = self._base_path.resolve()
        candidate_names = [name] if Path(name).suffix else [
            f"{name}.yaml",
            f"{name}.yml",
            f"{name}.json",
            f"{name}.j2",
        ]

        for candidate in candidate_names:
            path = (base_path / candidate).resolve()
            try:
                path.relative_to(base_path)
            except ValueError:
                raise ValueError(f"不正なテンプレートパスです: {name}")
            if path.exists():
                return path

        raise FileNotFoundError(f"テンプレート {name} が見つかりません: {self._base_path}")

    def _emit_event(self, event_type: str, **payload: Any) -> None:
        """イベントフックがあれば通知する"""
        if self._event_hook:
            self._event_hook({"type": event_type, **payload})

    def _read_file(self, path: Path):
        """拡張子ごとにテンプレートを読み込む"""
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            with open(path, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
            template_body = str(meta.get("template", ""))
            return meta, template_body

        if suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            template_body = str(meta.get("template", ""))
            return meta, template_body

        if suffix == ".j2":
            with open(path, "r", encoding="utf-8") as f:
                template_body = f.read()
            meta_path_yaml = path.with_suffix(".yaml")
            meta_path_json = path.with_suffix(".json")
            if meta_path_yaml.exists():
                with open(meta_path_yaml, "r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f) or {}
            elif meta_path_json.exists():
                with open(meta_path_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            else:
                raise FileNotFoundError(
                    f"{path.name} のメタデータ (.yaml/.json) が見つかりません"
                )
            meta["template"] = template_body
            return meta, template_body

        raise ValueError(f"未対応のテンプレート拡張子です: {suffix}")

    def _is_expired(self, revision: TemplateRevision) -> bool:
        """TTL 失効判定"""
        return (self._now() - revision.loaded_at) >= timedelta(seconds=self._ttl_seconds)
