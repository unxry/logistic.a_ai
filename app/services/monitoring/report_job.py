"""DailyAnalyticsReportJob — ежедневный «Отчёт LogistAI» через Scheduler."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.scheduler import Interval, JobContext, JobSpec
from app.core.models.severity import Severity
from app.core.models.sources import SourceHealth
from app.core.ports import MatchingRepository
from app.services.monitoring.collector import AnalyticsCollector

_DAY_SECONDS = 24 * 60 * 60


class DailyAnalyticsReportJob:
    """Ежедневная сводка: грузы, подбор, прибыль, ошибки источников."""

    def __init__(
        self,
        *,
        matching_repository: MatchingRepository,
        collector: AnalyticsCollector,
        health_provider: Callable[[], Mapping[str, SourceHealth]],
        interval_seconds: float = _DAY_SECONDS,
    ) -> None:
        self._matching = matching_repository
        self._collector = collector
        self._health_provider = health_provider
        self._spec = JobSpec(
            name="daily_analytics_report",
            schedule=Interval(seconds=interval_seconds, run_immediately=False),
            timeout_seconds=60.0,
        )

    @property
    def spec(self) -> JobSpec:
        """Описание задачи для Scheduler."""
        return self._spec

    async def run(self, context: JobContext) -> None:
        """Сформировать отчёт и отправить через Notification Center."""
        stats = await self._matching.get_statistics()
        routes = await self._matching.route_statistics()
        lines = [
            f"🚚 Найдено грузов: {self._collector.total_cargo_received()}",
            f"✅ Подходящих: {stats.compatible_count}",
        ]
        if stats.best_routes:
            lines.append(f"⭐ Лучший маршрут: {stats.best_routes[0]}")
        if stats.average_profit > 0:
            lines.append(f"💰 Средняя прибыль: {stats.average_profit:.0f} ₽")
        if routes.average_profit_per_km > 0:
            lines.append(f"📈 Средняя ставка: {routes.average_profit_per_km:.0f} ₽/км")
        failures = {
            source_id: self._collector.source_failures[source_id]
            for source_id in self._health_provider()
        }
        if failures:
            lines.append("Ошибки источников:")
            lines.extend(f"{source_id}: {count}" for source_id, count in failures.items())

        notification = (
            NotificationBuilder()
            .title("Отчёт LogistAI")
            .body("\n".join(lines))
            .severity(Severity.INFO)
            .category(NotificationCategory.SYSTEM)
            .source("monitoring")
            .trace_id(context.trace_id)
            .build()
        )
        await context.notifications.send(notification)
