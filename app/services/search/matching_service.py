"""CargoMatchingService — оркестрация подбора: репозиторий, события, уведомления.

Движок чист; этот сервис добавляет I/O: кандидаты из CargoRepository,
события CargoMatched/CargoRejected/SearchCompleted и уведомление о лучшем
грузе через Notification Center (категория CARGO).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.core.events import CargoMatched, CargoRejected, SearchCompleted
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.search import CargoMatch, CargoSearchQuery, SearchResult
from app.core.models.severity import Severity
from app.core.ports import CargoRepository, EventPublisher, NotificationSender
from app.services.search.engine import CargoSearchEngine

logger = logging.getLogger(__name__)

_SOURCE = "search"


class CargoMatchingService:
    """Публичный вход подбора грузов."""

    def __init__(
        self,
        *,
        engine: CargoSearchEngine,
        repository: CargoRepository,
        event_bus: EventPublisher,
        notifications: NotificationSender,
    ) -> None:
        self._engine = engine
        self._repository = repository
        self._events = event_bus
        self._notifications = notifications

    async def search(
        self,
        query: CargoSearchQuery,
        vehicle: VehicleProfile,
        *,
        trace_id: str | None = None,
    ) -> SearchResult:
        """Найти и ранжировать грузы под профиль; опубликовать события."""
        trace = trace_id if trace_id else uuid4().hex
        candidates = await self._repository.search(query)
        result = self._engine.search(query, vehicle, candidates, trace_id=trace)

        for match in result.matches:
            if match.compatible:
                self._events.publish(
                    CargoMatched(
                        cargo_id=match.cargo_id,
                        vehicle_profile_id=vehicle.id,
                        score=match.score,
                        trace_id=trace,
                    )
                )
            else:
                self._events.publish(
                    CargoRejected(
                        cargo_id=match.cargo_id,
                        vehicle_profile_id=vehicle.id,
                        reasons=match.compatibility_result.rejection_reasons,
                        trace_id=trace,
                    )
                )
        self._events.publish(
            SearchCompleted(
                query_id=query.id,
                trace_id=trace,
                total_candidates=result.total_candidates,
                matched=len(result.compatible_matches),
            )
        )
        logger.info(
            "Поиск: кандидатов %d, отсеяно %d, совместимых %d",
            result.total_candidates,
            result.prefiltered_out,
            len(result.compatible_matches),
        )
        return result

    async def find_best(
        self,
        vehicle: VehicleProfile,
        query: CargoSearchQuery | None = None,
        *,
        notify: bool = True,
    ) -> CargoMatch | None:
        """Лучший совместимый груз (и уведомление о нём, если найден)."""
        effective_query = query if query is not None else CargoSearchQuery.create(vehicle.id)
        result = await self.search(effective_query, vehicle)
        best = result.best
        if best is not None and notify:
            await self._notify_match(best, vehicle, result.trace_id)
        return best

    def match_single(self, cargo: Cargo, vehicle: VehicleProfile) -> CargoMatch:
        """Оценить один груз без запроса (делегирует движку)."""
        return self._engine.match_single(cargo, vehicle, CargoSearchQuery.create(vehicle.id))

    async def _notify_match(
        self, match: CargoMatch, vehicle: VehicleProfile, trace_id: str
    ) -> None:
        cargo = match.cargo
        route = " → ".join(part for part in (cargo.loading_region, cargo.unloading_region) if part)
        lines: list[str] = []
        if route:
            lines.append(route)
        if cargo.weight_kg is not None:
            lines.append(f"Вес: {cargo.weight_kg} кг")
        if cargo.payment_amount is not None:
            lines.append(f"Цена: {cargo.payment_amount:.0f} ₽")
        lines.append(f"Совместимость: {match.compatibility_result.score}%")
        lines.append(f"Оценка: {match.score}/100 — подходит под {vehicle.name}")

        builder = (
            NotificationBuilder()
            .title("🚚 Найден подходящий груз")
            .body("\n".join(lines))
            .severity(Severity.SUCCESS)
            .category(NotificationCategory.CARGO)
            .source(_SOURCE)
            .module(cargo.source_id)
            .payload_item("cargo_id", cargo.id)
            .trace_id(trace_id)
        )
        if cargo.url:
            builder.open_cargo(cargo.url)
        elif cargo.source_id == "ati":
            builder.open_ati_search()
        try:
            await self._notifications.send(builder.build())
        except Exception:
            logger.exception("Не удалось отправить уведомление о найденном грузе")
