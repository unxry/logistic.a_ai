"""NotificationDispatcher — параллельная доставка по каналам.

Берёт форматтер из FormatterRegistry, канал из ChannelRegistry, отправляет
через ``asyncio.gather`` с полной изоляцией ошибок и собирает DeliveryReport
с таймингами и trace_id.
"""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.core.clock import utc_now
from app.core.models.notification import DeliveryReport, DeliveryResult, Notification
from app.services.notifications.registries import ChannelRegistry, FormatterRegistry


class NotificationDispatcher:
    """Доставка уведомления по списку каналов."""

    def __init__(self, channels: ChannelRegistry, formatters: FormatterRegistry) -> None:
        self._channels = channels
        self._formatters = formatters

    async def dispatch(
        self, notification: Notification, channel_ids: tuple[str, ...]
    ) -> DeliveryReport:
        """Отправить во все каналы параллельно; отчёт — всегда, без исключений."""
        started_at = utc_now()
        started = perf_counter()
        results = await asyncio.gather(
            *(self._send_one(notification, channel_id) for channel_id in channel_ids)
        )
        return DeliveryReport(
            notification_id=notification.id,
            results=tuple(results),
            trace_id=notification.trace_id,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=int((perf_counter() - started) * 1000),
        )

    async def _send_one(self, notification: Notification, channel_id: str) -> DeliveryResult:
        channel = self._channels.get(channel_id)
        if channel is None:
            return DeliveryResult(channel_id=channel_id, ok=False, error="Канал не зарегистрирован")
        text = self._formatters.get(channel_id).format(notification)
        try:
            return await channel.send(notification, text)
        except Exception as exc:  # канал обязан не бросать, но страхуемся
            return DeliveryResult(channel_id=channel_id, ok=False, error=str(exc))
