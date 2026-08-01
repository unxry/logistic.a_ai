"""Порт хранилища секретов (Bot Token и т.п.)."""

from __future__ import annotations

from typing import Protocol

# Имена секретов — часть контракта: адаптеры и сервисы используют константы,
# а не «магические» строки.
TELEGRAM_BOT_TOKEN_KEY = "telegram_bot_token"
TELEGRAM_CHAT_ID_KEY = "telegram_chat_id"


class SecretStore(Protocol):
    """Безопасное хранилище секретов (реализация: Keychain через keyring).

    Секреты никогда не хранятся в настройках-JSON и не пишутся в логи.
    """

    def get(self, name: str) -> str | None:
        """Прочитать секрет; ``None`` — секрет не задан."""
        ...

    def set(self, name: str, value: str) -> None:
        """Записать секрет."""
        ...

    def delete(self, name: str) -> None:
        """Удалить секрет (отсутствующий — не ошибка)."""
        ...
