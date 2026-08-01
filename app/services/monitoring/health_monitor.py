"""SourceHealthMonitor — контроль доступности источников.

Источник в FAILED дольше порога → одно уведомление («⚠️ … недоступен N минут»);
после восстановления сторожок сбрасывается.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime

from app.core.clock import utc_now
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.severity import Severity
from app.core.models.sources import SourceHealth, SourceStatus
from app.core.ports import NotificationSender

logger = logging.getLogger(__name__)


class SourceHealthMonitor:
    """Наблюдение за здоровьем источников."""

    def __init__(
        self,
        *,
        health_provider: Callable[[], Mapping[str, SourceHealth]],
        notifications: NotificationSender,
        clock: Callable[[], datetime] = utc_now,
        unavailable_after_minutes: float = 15.0,
    ) -> None:
        self._health_provider = health_provider
        self._notifications = notifications
        self._clock = clock
        self._threshold_minutes = unavailable_after_minutes
        self._notified: set[str] = set()

    async def check_all(self) -> tuple[str, ...]:
        """Проверить все источники; вернуть id, о которых уведомили."""
        alerted: list[str] = []
        now = self._clock()
        for source_id, health in self._health_provider().items():
            if health.status is not SourceStatus.FAILED:
                self._notified.discard(source_id)
                continue
            minutes = self._minutes_down(health, now)
            if minutes < self._threshold_minutes or source_id in self._notified:
                continue
            await self._alert(source_id, minutes)
            self._notified.add(source_id)
            alerted.append(source_id)
        return tuple(alerted)

    @staticmethod
    def _minutes_down(health: SourceHealth, now: datetime) -> float:
        anchor = health.last_success or health.last_error_at
        if anchor is None:
            return float("inf")
        return (now - anchor).total_seconds() / 60

    async def _alert(self, source_id: str, minutes: float) -> None:
        duration = "давно" if minutes == float("inf") else f"{minutes:.0f} минут"
        notification = (
            NotificationBuilder()
            .title(f"⚠️ Источник «{source_id}» недоступен {duration}")
            .body("Проверьте учётные данные и доступность сервиса.")
            .severity(Severity.WARNING)
            .category(NotificationCategory.MONITOR)
            .source("monitoring")
            .module(source_id)
            .build()
        )
        try:
            await self._notifications.send(notification)
        except Exception:
            logger.exception("Не удалось отправить уведомление о недоступности источника")
