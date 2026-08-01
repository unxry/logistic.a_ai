"""RouteService — маршруты для подбора: провайдер + деньги + кэш + события.

Провайдер (порт RouteProvider) отдаёт геометрию; деньги досчитывает
RouteCostCalculator. Неизвестное провайдеру направление — синтетическая
оценка по расстоянию из объявления (низкая уверенность; событие не
публикуется — это не рассчитанный маршрут). Кэш процесса ограничен и не
переживает перезапуск: реальные провайдеры платные, персистентный кэш
появится вместе с ними, за этим же фасадом.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.core.events import RouteCalculated
from app.core.models.logistics.cargo import Cargo
from app.core.models.routes import Route, RouteEstimate
from app.core.ports import EventPublisher, RouteProvider
from app.services.routes.cost_calculator import RouteCostCalculator

logger = logging.getLogger(__name__)

_CACHE_LIMIT = 256


class RouteService:
    """Оценка маршрутов и холостых прогонов для подбора грузов."""

    def __init__(
        self,
        *,
        provider: RouteProvider | None,
        costs: RouteCostCalculator,
        event_bus: EventPublisher,
        cache_limit: int = _CACHE_LIMIT,
    ) -> None:
        self._provider = provider
        self._costs = costs
        self._events = event_bus
        self._cache: dict[tuple[str, str], RouteEstimate] = {}
        self._cache_limit = cache_limit

    @property
    def costs(self) -> RouteCostCalculator:
        """Калькулятор тарифов (для потребителей, считающих вручную)."""
        return self._costs

    async def estimate(
        self, origin: str, destination: str, *, trace_id: str = ""
    ) -> RouteEstimate | None:
        """Маршрут точка→точка; ``None`` — нет провайдера или направление неизвестно."""
        origin = origin.strip()
        destination = destination.strip()
        if not origin or not destination or self._provider is None:
            return None
        key = (origin, destination)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            raw = await self._provider.calculate_route(origin, destination)
        except Exception:
            logger.exception("Провайдер маршрутов не ответил (%s → %s)", origin, destination)
            return None
        if raw is None:
            return None
        estimate = self._costs.enrich(raw)
        self._remember(key, estimate)
        self._events.publish(
            RouteCalculated(route=Route.create(origin, destination, estimate), trace_id=trace_id)
        )
        return estimate

    async def estimate_for_cargo(self, cargo: Cargo, *, trace_id: str = "") -> RouteEstimate | None:
        """Маршрут груза; провайдер молчит — синтетика из расстояния объявления."""
        estimate = await self.estimate(
            cargo.loading_region, cargo.unloading_region, trace_id=trace_id
        )
        if estimate is not None:
            return estimate
        if cargo.distance_km is not None and cargo.distance_km > 0:
            return self._costs.synthetic_estimate(cargo.distance_km)
        return None

    async def empty_run_cost(self, origin: str, destination: str, *, trace_id: str = "") -> Decimal:
        """Стоимость холостого подгона; неизвестное направление — честный 0."""
        origin = origin.strip()
        destination = destination.strip()
        if not origin or not destination or origin == destination:
            return Decimal(0)
        estimate = await self.estimate(origin, destination, trace_id=trace_id)
        if estimate is None or estimate.distance_km <= 0:
            return Decimal(0)
        return self._costs.empty_run_cost(estimate.distance_km)

    def _remember(self, key: tuple[str, str], estimate: RouteEstimate) -> None:
        if len(self._cache) >= self._cache_limit:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = estimate
