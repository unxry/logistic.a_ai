"""Встроенные задачи планировщика."""

from __future__ import annotations

from datetime import timedelta

from app.core.models.scheduler import Interval, JobContext, JobSpec

_DAY_SECONDS = 24 * 60 * 60


class HistoryCleanupJob:
    """Ежедневная чистка журнала по retention из настроек.

    Образец задачи: все зависимости — из JobContext, никаких импортов
    сервисов; идемпотентна.
    """

    def __init__(self, interval_seconds: float = _DAY_SECONDS) -> None:
        self._spec = JobSpec(
            name="history_cleanup",
            schedule=Interval(seconds=interval_seconds, run_immediately=False),
            timeout_seconds=60.0,
        )

    @property
    def spec(self) -> JobSpec:
        """Описание задачи."""
        return self._spec

    async def run(self, context: JobContext) -> None:
        """Удалить записи журнала старше retention_days."""
        retention_days = context.settings().history.retention_days
        threshold = context.clock() - timedelta(days=retention_days)
        removed = await context.history.prune(before=threshold)
        context.logger.info(
            "Журнал очищен: удалено %d записей старше %d дней", removed, retention_days
        )
