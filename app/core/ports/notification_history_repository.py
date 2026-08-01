"""Порт истории уведомлений."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.core.models.notification_history import NotificationHistoryEntry, NotificationOpenState


class NotificationHistoryRepository(Protocol):
    """Хранилище истории уведомлений для Timeline и аналитики."""

    async def add(self, entry: NotificationHistoryEntry) -> None:
        """Добавить запись уведомления."""
        ...

    async def query(
        self,
        *,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[NotificationHistoryEntry]:
        """Выбрать уведомления (новые — первыми)."""
        ...

    async def mark_opened(self, notification_id: str) -> None:
        """Отметить уведомление открытым пользователем."""
        ...

    async def open_state(self, notification_id: str) -> NotificationOpenState:
        """Текущее состояние открытия уведомления."""
        ...
