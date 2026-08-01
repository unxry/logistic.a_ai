"""Порт публикации событий.

Позволяет инфраструктуре и сервисам публиковать события, не импортируя
``app.buses`` (контракты: infrastructure → только core). ``EventBus``
удовлетворяет порту структурно — регистрация не нужна.
"""

from __future__ import annotations

from typing import Protocol

from app.core.events import Event


class EventPublisher(Protocol):
    """Публикация доменных событий."""

    def publish(self, event: Event) -> None:
        """Доставить событие подписчикам."""
        ...
