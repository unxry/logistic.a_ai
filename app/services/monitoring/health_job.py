"""SourceHealthCheckJob — минутная проверка здоровья источников.

Обычный Job для Scheduler: зовёт SourceHealthMonitor.check_all(), который
шлёт «⚠️ источник недоступен N минут» один раз до восстановления
(Notification Center — единственный канал ошибок мониторинга).
"""

from __future__ import annotations

from app.core.models.scheduler import Interval, JobContext, JobSpec
from app.services.monitoring.health_monitor import SourceHealthMonitor

_DEFAULT_INTERVAL_SECONDS = 60.0


class SourceHealthCheckJob:
    """Периодический прогон монитора здоровья источников."""

    def __init__(
        self,
        monitor: SourceHealthMonitor,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._monitor = monitor
        self._spec = JobSpec(
            name="source_health_check",
            schedule=Interval(seconds=interval_seconds, run_immediately=False),
            timeout_seconds=30.0,
        )

    @property
    def spec(self) -> JobSpec:
        """Описание задачи для Scheduler."""
        return self._spec

    async def run(self, context: JobContext) -> None:
        """Проверить все источники (уведомления шлёт монитор)."""
        await self._monitor.check_all()
