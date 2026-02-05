"""認証トークンの安全な保存を提供する。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import warnings

import keyring
from keyring.errors import KeyringError


class TokenManager:
    """認証トークンの保存と取得を管理する。"""

    def __init__(self, keyring_service: str = "magi", fallback_path: Path | None = None) -> None:
        """TokenManagerを初期化する。

        Args:
            keyring_service: keyringに保存する際のサービス名。
            fallback_path: keyringが使えない場合の保存先。
        """

        self._keyring_service = keyring_service
        self._fallback_path = fallback_path or Path.home() / ".magi" / "tokens.json"
        self._use_keyring = True

    def set_token(self, service: str, token: str) -> None:
        """トークンを保存する。

        Args:
            service: サービス名（例: magi.claude）。
            token: 保存するアクセストークン。
        """

        if self._use_keyring:
            try:
                keyring.set_password(self._keyring_service, service, token)
                return
            except KeyringError as exc:
                self._switch_to_fallback(exc)

        self._set_token_fallback(service, token)

    def get_token(self, service: str) -> str | None:
        """トークンを取得する。

        Args:
            service: サービス名（例: magi.claude）。

        Returns:
            トークン。存在しない場合はNone。
        """

        if self._use_keyring:
            try:
                return keyring.get_password(self._keyring_service, service)
            except KeyringError as exc:
                self._switch_to_fallback(exc)

        return self._get_token_fallback(service)

    def delete_token(self, service: str) -> None:
        """トークンを削除する。

        Args:
            service: サービス名（例: magi.claude）。
        """

        if self._use_keyring:
            try:
                keyring.delete_password(self._keyring_service, service)
                return
            except KeyringError as exc:
                self._switch_to_fallback(exc)

        self._delete_token_fallback(service)

    def _switch_to_fallback(self, exc: Exception) -> None:
        if self._use_keyring:
            warnings.warn(
                "keyringが利用できないため、ローカルファイルに保存します。",
                RuntimeWarning,
                stacklevel=2,
            )
            self._use_keyring = False

    def _read_fallback_tokens(self) -> dict[str, str]:
        if not self._fallback_path.exists():
            return {}

        self._ensure_fallback_permissions(self._fallback_path)
        try:
            with self._fallback_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError:
            warnings.warn(
                "トークン保存ファイルの形式が不正です。空として扱います。",
                RuntimeWarning,
                stacklevel=2,
            )
            return {}

        if not isinstance(data, dict):
            return {}

        return {str(key): str(value) for key, value in data.items()}

    def _write_fallback_tokens(self, tokens: dict[str, str]) -> None:
        self._fallback_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._fallback_path.open("w", encoding="utf-8") as file:
            json.dump(tokens, file, ensure_ascii=False, indent=2)
        self._ensure_fallback_permissions(self._fallback_path)

    def _ensure_fallback_permissions(self, path: Path) -> None:
        if path.exists():
            os.chmod(path, 0o600)

    def _set_token_fallback(self, service: str, token: str) -> None:
        tokens = self._read_fallback_tokens()
        tokens[service] = token
        self._write_fallback_tokens(tokens)

    def _get_token_fallback(self, service: str) -> str | None:
        tokens = self._read_fallback_tokens()
        return tokens.get(service)

    def _delete_token_fallback(self, service: str) -> None:
        tokens = self._read_fallback_tokens()
        if service in tokens:
            tokens.pop(service)
            self._write_fallback_tokens(tokens)
