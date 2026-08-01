"""Notification Center — центральная система уведомлений платформы.

Единственная точка входа для всех модулей: ``NotificationService.send(...)``.
Никто, кроме Notification Center, не знает о каналах, форматтерах, журнале.
"""

from app.services.notifications.cooldown import NotificationCooldownPolicy
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.notifications.handlers import SendNotificationHandler
from app.services.notifications.plain_formatter import PlainTextFormatter
from app.services.notifications.registries import ChannelRegistry, FormatterRegistry
from app.services.notifications.router import NotificationRouter
from app.services.notifications.service import NotificationService

__all__ = [
    "ChannelRegistry",
    "FormatterRegistry",
    "NotificationCooldownPolicy",
    "NotificationDispatcher",
    "NotificationRouter",
    "NotificationService",
    "PlainTextFormatter",
    "SendNotificationHandler",
]
