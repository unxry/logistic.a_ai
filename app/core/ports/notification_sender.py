"""Порт отправки уведомлений.

Позволяет Scheduler'у, источникам и плагинам слать уведомления, не зная
NotificationService: сервис Notification Center удовлетворяет порту
структурно (метод ``send``).
"""

from __future__ import annotations

from typing import Protocol

from app.core.models.notification import Notification


class NotificationSender(Protocol):
    """Единственная операция, которую знают модули платформы."""

    async def send(self, notification: Notification) -> None:
        """Поставить уведомление в доставку."""
        ...
