"""События Telegram-подключения."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.connection import ConnectionState


@dataclass(frozen=True, slots=True)
class TelegramStatusChanged(Event):
    """Состояние Telegram-подключения изменилось (для статус-бара и журнала)."""

    state: ConnectionState
    detail: str = ""
