"""Хранилища секретов: системный Keychain (keyring) и NullSecretStore.

Секреты (Bot Token) никогда не пишутся в JSON-настройки и логи
(ADR-0008, ADR-0010).
"""

from __future__ import annotations

import keyring
import keyring.errors

from app.core.errors import SecretStoreError

_SERVICE_NAME = "LogistAI"


class KeyringSecretStore:
    """SecretStore на системном хранилище.

    macOS — Keychain, Windows — Credential Manager (та же библиотека keyring —
    кроссплатформенность бесплатно). Ошибки backend'а переводятся в доменную
    ``SecretStoreError``.
    """

    def __init__(self, service_name: str = _SERVICE_NAME) -> None:
        self._service_name = service_name

    def get(self, name: str) -> str | None:
        """Прочитать секрет; ``None`` — не задан."""
        try:
            return keyring.get_password(self._service_name, name)
        except keyring.errors.KeyringError as exc:
            raise SecretStoreError(f"Хранилище секретов недоступно: {exc}") from exc

    def set(self, name: str, value: str) -> None:
        """Записать секрет."""
        try:
            keyring.set_password(self._service_name, name, value)
        except keyring.errors.KeyringError as exc:
            raise SecretStoreError(f"Не удалось записать секрет: {exc}") from exc

    def delete(self, name: str) -> None:
        """Удалить секрет; отсутствующий — не ошибка (контракт порта)."""
        try:
            keyring.delete_password(self._service_name, name)
        except keyring.errors.PasswordDeleteError:
            return
        except keyring.errors.KeyringError as exc:
            raise SecretStoreError(f"Не удалось удалить секрет: {exc}") from exc


class NullSecretStore:
    """SecretStore в памяти — для тестов и деградированного режима.

    Между запусками ничего не сохраняет. В проде допустим только как
    осознанный фолбэк с предупреждением в логе.
    """

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        """Прочитать секрет из памяти."""
        return self._secrets.get(name)

    def set(self, name: str, value: str) -> None:
        """Записать секрет в память."""
        self._secrets[name] = value

    def delete(self, name: str) -> None:
        """Удалить секрет из памяти (отсутствующий — не ошибка)."""
        self._secrets.pop(name, None)
