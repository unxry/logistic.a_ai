"""События жизненного цикла приложения и сквозные события."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event


@dataclass(frozen=True, slots=True)
class AppStarted(Event):
    """Приложение запущено и собрано."""


@dataclass(frozen=True, slots=True)
class AppClosing(Event):
    """Приложение завершает работу: сервисы должны остановиться корректно."""


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Event):
    """Произошла ошибка, о которой стоит знать UI (статус-бар) и журналу."""

    source: str
    message: str


@dataclass(frozen=True, slots=True)
class LogRecordAdded(Event):
    """В лог добавлена запись (для живой ленты логов в UI)."""

    level: str
    logger_name: str
    message: str
