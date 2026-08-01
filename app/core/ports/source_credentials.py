"""Порт доступа к учётным данным источников.

Ядро не знает про Keychain: конфигурация источника хранит только
``credentials_reference``, по которой провайдер достаёт поля
(login, password, api_key, token) из системного хранилища секретов.
"""

from __future__ import annotations

from typing import Protocol

# Общепринятые имена полей учётных данных источников.
CRED_LOGIN = "login"
CRED_PASSWORD = "password"
CRED_API_KEY = "api_key"
CRED_TOKEN = "token"


class SourceCredentialProvider(Protocol):
    """Чтение секретов источника по ссылке из конфигурации."""

    def get(self, credentials_reference: str, field: str) -> str | None:
        """Секретное поле; ``None`` — не задано."""
        ...
