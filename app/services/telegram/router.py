"""TelegramCommandRouter — маршрутизация команд бота без if-else (Stage 9.7).

Роутер — словарь «команда → обработчик»: обработчики регистрирует
composition root (данные из сервисов + тексты из инфраструктуры),
клиент Telegram о командах не знает вообще.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

#: Обработчик команды: принимает аргументы после команды, возвращает HTML.
CommandHandler = Callable[[str], Awaitable[str]]


class TelegramCommandRouter:
    """Диспетчер команд бота (/start, /status, …)."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._descriptions: dict[str, str] = {}
        self._fallback: Callable[[], str] | None = None

    def register(self, command: str, handler: CommandHandler, *, description: str) -> None:
        """Зарегистрировать команду (повторная регистрация — ошибка сборки)."""
        normalized = command.strip().lower()
        if not normalized.startswith("/"):
            raise ValueError(f"Команда должна начинаться с «/»: {command!r}")
        if normalized in self._handlers:
            raise ValueError(f"Команда {normalized} уже зарегистрирована")
        self._handlers[normalized] = handler
        self._descriptions[normalized] = description

    def set_fallback(self, fallback: Callable[[], str]) -> None:
        """Ответ на неизвестную команду (подсказка со списком)."""
        self._fallback = fallback

    def commands(self) -> tuple[tuple[str, str], ...]:
        """(команда, описание) — для /help, /start и настройки BotFather."""
        return tuple(self._descriptions.items())

    async def dispatch(self, text: str) -> str | None:
        """Обработать текст сообщения; не команда — ``None`` (бот молчит)."""
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        command, _, arguments = stripped.partition(" ")
        # «/status@LogistAIBot» в группах — отрезаем адресата.
        command = command.split("@", 1)[0].lower()
        handler = self._handlers.get(command)
        if handler is None:
            logger.info("Telegram-бот: неизвестная команда %s", command)
            return self._fallback() if self._fallback is not None else None
        return await handler(arguments.strip())
