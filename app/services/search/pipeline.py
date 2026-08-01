"""RecommendationPipeline — от CargoReceived до рекомендации (Stage 9.5/9.6).

Единственный связующий слой конвейера:
CargoReceived → дедупликация (NEW/UPDATED/DUPLICATE) → CargoRepository →
Search Engine → Intelligent Matching → уведомление о лучшем → колбэк дашборда.
Обновившийся груз (цена/маршрут/вес) публикуется событием CargoUpdated и
снова участвует в подборе — изменение цены может сделать его лучшим.

Пайплайн знает только порты, сервисы и модели ядра; UI получает результат
через инжектированный колбэк ``on_ranked`` (композиция в bootstrap) —
services не импортируют ui.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from app.buses import EventBus
from app.core.events import CargoReceived, CargoUpdated
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.matching import IntelligentCargoMatch, MatchingContext
from app.core.models.search import CargoSearchQuery
from app.core.ports import CargoRepository, EventPublisher
from app.services.matching import IntelligentMatchingService
from app.services.search.matching_service import CargoMatchingService
from app.services.sources.dedup import CargoDeduplicationService, DeduplicationStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """Итог обработки одной пачки грузов (для журналирования и smoke)."""

    source_id: str
    trace_id: str
    received: int
    new_count: int
    duplicates: int
    updated_count: int = 0
    compatible: int = 0
    prefilter_rejected: int = 0
    compatibility_rejected: int = 0
    ranked_count: int = 0
    notifications_created: int = 0
    best_cargo_id: str = ""
    best_route: str = ""
    best_score: int = 0


class RecommendationPipeline:
    """Подписчик CargoReceived, доводящий грузы до рекомендации."""

    def __init__(
        self,
        *,
        repository: CargoRepository,
        matching: CargoMatchingService,
        intelligent: IntelligentMatchingService,
        deduplicator: CargoDeduplicationService,
        vehicle_provider: Callable[[], VehicleProfile | None],
        driver_provider: Callable[[], DriverProfile],
        location_provider: Callable[[], str] = lambda: "",
        on_ranked: Callable[[tuple[IntelligentCargoMatch, ...]], None] | None = None,
        duplicates_sink: Callable[[str, int], None] | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._matching = matching
        self._intelligent = intelligent
        self._dedup = deduplicator
        self._vehicle_provider = vehicle_provider
        self._driver_provider = driver_provider
        self._location_provider = location_provider
        self._on_ranked = on_ranked
        self._duplicates_sink = duplicates_sink
        self._events = event_publisher
        self._tasks: set[asyncio.Task[PipelineReport]] = set()
        self.last_report: PipelineReport | None = None

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    def attach(self, bus: EventBus) -> None:
        """Подписаться на CargoReceived (bootstrap)."""
        bus.subscribe(CargoReceived, self._on_cargo_received)

    def detach(self, bus: EventBus) -> None:
        """Отписаться (остановка приложения)."""
        bus.unsubscribe(CargoReceived, self._on_cargo_received)

    async def wait_idle(self) -> None:
        """Дождаться завершения фоновых обработок (smoke и graceful shutdown)."""
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    # ── Обработка ─────────────────────────────────────────────────────────────

    def _on_cargo_received(self, event: CargoReceived) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Нет петли asyncio — пачка грузов не обработана")
            return
        task = loop.create_task(self.process(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _publish_updated(
        self, event: CargoReceived, cargo: Cargo, changes: tuple[str, ...]
    ) -> None:
        if self._events is None:
            return
        self._events.publish(
            CargoUpdated(
                source_id=event.source_id,
                trace_id=event.trace_id,
                cargo=cargo,
                changes=changes,
            )
        )

    async def process(self, event: CargoReceived) -> PipelineReport:
        """Полный конвейер одной пачки грузов."""
        fresh = []
        updated = 0
        duplicates = 0
        for cargo in event.items:
            verdict = self._dedup.assess(cargo)
            if verdict.status is DeduplicationStatus.DUPLICATE:
                duplicates += 1
                continue
            fresh.append(cargo)
            if verdict.status is DeduplicationStatus.UPDATED:
                updated += 1
                self._publish_updated(event, cargo, verdict.changes)
        if duplicates and self._duplicates_sink is not None:
            self._duplicates_sink(event.source_id, duplicates)

        report = PipelineReport(
            source_id=event.source_id,
            trace_id=event.trace_id,
            received=len(event.items),
            new_count=len(fresh) - updated,
            duplicates=duplicates,
            updated_count=updated,
        )
        if not fresh:
            logger.info(
                "Источник «%s»: новых грузов нет (дубликатов %d)", event.source_id, duplicates
            )
            self.last_report = report
            return report

        await self._repository.save_many(tuple(fresh))

        vehicle = self._vehicle_provider()
        if vehicle is None:
            logger.info("Подбор пропущен: активный профиль транспорта не настроен")
            self.last_report = report
            return report

        query = CargoSearchQuery.create(vehicle.id)
        result = await self._matching.search(query, vehicle, trace_id=event.trace_id)
        compatible = result.compatible_matches
        report = replace(
            report,
            compatible=len(compatible),
            prefilter_rejected=result.prefiltered_out,
            compatibility_rejected=len(result.matches) - len(compatible),
        )
        if not compatible:
            self.last_report = report
            return report

        context = MatchingContext(
            vehicle_profile=vehicle,
            driver_profile=self._driver_provider(),
            current_location=self._location_provider(),
        )
        ranked = await self._intelligent.rank(compatible, context, trace_id=event.trace_id)
        best = self._intelligent.select_from_ranked(ranked, context, trace_id=event.trace_id)
        if best is not None:
            await self._intelligent.notify_best(best, trace_id=event.trace_id)
            cargo = best.cargo_match.cargo
            route = " → ".join(p for p in (cargo.loading_region, cargo.unloading_region) if p)
            report = replace(
                report, best_cargo_id=cargo.id, best_route=route, best_score=best.final_score
            )
        report = replace(
            report,
            ranked_count=len(ranked),
            notifications_created=1 if best is not None else 0,
        )
        if self._on_ranked is not None and ranked:
            self._on_ranked(ranked)
        self.last_report = report
        return report
