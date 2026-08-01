"""События жизненного цикла уведомлений (Notification Center).

Queued → Sending → Delivered | Failed. Dashboard подписывается и показывает
живую активность; все события несут trace_id для корреляции.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.notification import DeliveryReport, Notification


@dataclass(frozen=True, slots=True)
class NotificationQueued(Event):
    """Уведомление поставлено в очередь Notification Center."""

    notification: Notification


@dataclass(frozen=True, slots=True)
class NotificationSending(Event):
    """Начата доставка по выбранным каналам."""

    notification_id: str
    trace_id: str
    channels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotificationDelivered(Event):
    """Уведомление доставлено (хотя бы в один канал)."""

    report: DeliveryReport


@dataclass(frozen=True, slots=True)
class NotificationFailed(Event):
    """Уведомление не удалось доставить ни в один канал."""

    report: DeliveryReport
