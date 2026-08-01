"""Провайдер учётных данных источников поверх SecretStore.

Ключ секрета: ``source:{reference}:{field}`` — например,
``source:ati_main:api_key``. Ядро не знает про Keychain: реализация
использует порт SecretStore (Keychain на macOS, Credential Manager на Windows).
"""

from __future__ import annotations

from app.core.ports import SecretStore


class KeychainSourceCredentialProvider:
    """SourceCredentialProvider на системном хранилище секретов."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._secrets = secret_store

    def get(self, credentials_reference: str, field: str) -> str | None:
        """Секретное поле источника; ``None`` — не задано."""
        if not credentials_reference:
            return None
        return self._secrets.get(f"source:{credentials_reference}:{field}")
