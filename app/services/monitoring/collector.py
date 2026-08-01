"""Сбор аналитики из событий платформы.

AnalyticsCollector — счётчики в памяти (источники, подбор, задачи);
DecisionPersister — асинхронно сохраняет каждое MatchingDecisionCreated
в хранилище решений. Подписка — в bootstrap (attach).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from decimal import Decimal

from app.buses import EventBus
from app.core.events import (
    CargoMatched,
    CargoReceived,
    CargoRejected,
    JobFailed,
    MatchingDecisionCreated,
    ProfitCalculated,
    RouteCalculated,
    SourceCompleted,
    SourceFailed,
)
from app.core.models.analytics import SourceAnalytics
from app.core.models.sources import SourceHealth
from app.core.ports import MatchingRepository

logger = logging.getLogger(__name__)


class AnalyticsCollector:
    """Счётчики наблюдаемости, обновляемые событиями."""

    def __init__(self) -> None:
        self.cargo_received: defaultdict[str, int] = defaultdict(int)
        self.source_runs: defaultdict[str, int] = defaultdict(int)
        self.source_failures: defaultdict[str, int] = defaultdict(int)
        self.duplicate_counts: defaultdict[str, int] = defaultdict(int)
        self.matched_count = 0
        self.rejected_count = 0
        self.jobs_failed = 0
        self.routes_calculated = 0
        self.profits_calculated = 0
        self._route_distance_total = 0.0
        self._profit_per_km_total = Decimal(0)
        self._price_sums: defaultdict[str, Decimal] = defaultdict(lambda: Decimal(0))
        self._price_counts: defaultdict[str, int] = defaultdict(int)
        self._source_routes: defaultdict[str, Counter[str]] = defaultdict(Counter)

    def attach(self, bus: EventBus) -> None:
        """Подписаться на события платформы (bootstrap)."""
        bus.subscribe(CargoReceived, self._on_cargo_received)
        bus.subscribe(SourceCompleted, self._on_source_completed)
        bus.subscribe(SourceFailed, self._on_source_failed)
        bus.subscribe(CargoMatched, self._on_matched)
        bus.subscribe(CargoRejected, self._on_rejected)
        bus.subscribe(JobFailed, self._on_job_failed)
        bus.subscribe(RouteCalculated, self._on_route_calculated)
        bus.subscribe(ProfitCalculated, self._on_profit_calculated)

    def total_cargo_received(self) -> int:
        """Всего грузов получено (по всем источникам)."""
        return sum(self.cargo_received.values())

    def average_route_distance_km(self) -> float:
        """Средняя дистанция рассчитанных маршрутов (текущий процесс)."""
        if self.routes_calculated == 0:
            return 0.0
        return self._route_distance_total / self.routes_calculated

    def average_profit_per_km(self) -> Decimal:
        """Средняя расчётная прибыль на километр (текущий процесс)."""
        if self.profits_calculated == 0:
            return Decimal(0)
        return self._profit_per_km_total / self.profits_calculated

    def record_duplicates(self, source_id: str, count: int) -> None:
        """Учесть отсеянные дубликаты источника (зовёт пайплайн)."""
        self.duplicate_counts[source_id] += count

    def average_price(self, source_id: str) -> Decimal:
        """Средняя цена грузов источника; 0 — цен ещё не было."""
        count = self._price_counts[source_id]
        if count == 0:
            return Decimal(0)
        return self._price_sums[source_id] / count

    def top_routes(self, source_id: str, limit: int = 3) -> tuple[str, ...]:
        """Самые частые направления источника."""
        return tuple(route for route, _ in self._source_routes[source_id].most_common(limit))

    def source_analytics(
        self, source_id: str, health: SourceHealth | None = None
    ) -> SourceAnalytics:
        """Снапшот статистики источника (health добавляет тайминги)."""
        return SourceAnalytics(
            source_id=source_id,
            total_received=self.cargo_received[source_id],
            normalized_count=self.cargo_received[source_id],
            duplicate_count=self.duplicate_counts[source_id],
            failed_count=self.source_failures[source_id],
            average_response_time_ms=(health.average_duration_ms if health is not None else 0.0),
            last_success=health.last_success if health is not None else None,
        )

    # ── Обработчики ───────────────────────────────────────────────────────────

    def _on_cargo_received(self, event: CargoReceived) -> None:
        self.cargo_received[event.source_id] += len(event.items)
        for cargo in event.items:
            if cargo.payment_amount is not None:
                self._price_sums[event.source_id] += cargo.payment_amount
                self._price_counts[event.source_id] += 1
            if cargo.loading_region and cargo.unloading_region:
                route = f"{cargo.loading_region} → {cargo.unloading_region}"
                self._source_routes[event.source_id][route] += 1

    def _on_source_completed(self, event: SourceCompleted) -> None:
        self.source_runs[event.source_id] += 1

    def _on_source_failed(self, event: SourceFailed) -> None:
        self.source_failures[event.source_id] += 1

    def _on_matched(self, event: CargoMatched) -> None:
        self.matched_count += 1

    def _on_rejected(self, event: CargoRejected) -> None:
        self.rejected_count += 1

    def _on_job_failed(self, event: JobFailed) -> None:
        self.jobs_failed += 1

    def _on_route_calculated(self, event: RouteCalculated) -> None:
        self.routes_calculated += 1
        self._route_distance_total += event.route.distance_km

    def _on_profit_calculated(self, event: ProfitCalculated) -> None:
        if event.analysis.profit_per_km is None:
            return
        self.profits_calculated += 1
        self._profit_per_km_total += event.analysis.profit_per_km


class DecisionPersister:
    """Сохраняет каждое решение подбора в хранилище (fire-and-forget task)."""

    def __init__(self, repository: MatchingRepository) -> None:
        self._repository = repository
        self._tasks: set[asyncio.Task[None]] = set()  # защита задач от GC (RUF006)

    def attach(self, bus: EventBus) -> None:
        """Подписаться на MatchingDecisionCreated."""
        bus.subscribe(MatchingDecisionCreated, self._on_decision)

    def _on_decision(self, event: MatchingDecisionCreated) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Нет петли asyncio — решение не сохранено")
            return
        task = loop.create_task(self._save(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _save(self, event: MatchingDecisionCreated) -> None:
        try:
            await self._repository.save_decision(event.decision)
        except Exception:
            logger.exception("Не удалось сохранить решение подбора")
