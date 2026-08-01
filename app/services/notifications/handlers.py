"""Обработчик команды SendNotification (регистрируется в bootstrap)."""

from __future__ import annotations

from app.core.commands import SendNotification
from app.core.models.notification import DeliveryReport, Notification
from app.services.notifications.service import NotificationService


class SendNotificationHandler:
    """SendNotification → немедленная доставка с отчётом.

    Командный вызов интерактивен (UI, ручная отправка) — используется
    ``deliver_now``, чтобы вернуть DeliveryReport вызывающему.
    Потоковые уведомления модулей идут через ``send()`` (очередь).
    """

    def __init__(self, notification_service: NotificationService) -> None:
        self._notifications = notification_service

    async def __call__(self, command: SendNotification) -> DeliveryReport:
        """Собрать уведомление из команды и доставить немедленно."""
        notification = Notification.create(
            command.title,
            command.body,
            command.severity,
            command.channels,
        )
        return await self._notifications.deliver_now(notification)
