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
import time
from decimal import Decimal

from app.core.events import RouteCalculated
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.routes import (
    Route,
    RouteEstimate,
    RouteRequest,
    RouteVehicleParameters,
)
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
        self._cache: dict[str, RouteEstimate] = {}
        self._cache_limit = cache_limit

    @property
    def costs(self) -> RouteCostCalculator:
        """Калькулятор тарифов (для потребителей, считающих вручную)."""
        return self._costs

    async def estimate(
        self,
        origin: str,
        destination: str,
        *,
        trace_id: str = "",
        request: RouteRequest | None = None,
    ) -> RouteEstimate | None:
        """Маршрут точка→точка; ``None`` — нет провайдера или направление неизвестно."""
        origin = origin.strip()
        destination = destination.strip()
        if not origin or not destination or self._provider is None:
            return None
        route_request = self._prepare_request(
            request if request is not None else RouteRequest.simple(origin, destination)
        )
        key = self._memory_key(route_request)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            started = time.perf_counter()
            raw = await self._provider.calculate_route(origin, destination, request=route_request)
        except Exception:
            logger.exception("Провайдер маршрутов не ответил (%s → %s)", origin, destination)
            return None
        if raw is None:
            return None
        estimate = self._costs.enrich(raw)
        self._remember(key, estimate)
        self._events.publish(
            RouteCalculated(
                route=Route.create(origin, destination, estimate),
                trace_id=trace_id,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        return estimate

    async def estimate_for_cargo(
        self,
        cargo: Cargo,
        *,
        trace_id: str = "",
        vehicle_profile: VehicleProfile | None = None,
    ) -> RouteEstimate | None:
        """Маршрут груза; провайдер молчит — синтетика из расстояния объявления."""
        request = RouteRequest(
            origin=cargo.loading_region,
            destination=cargo.unloading_region,
            vehicle=RouteVehicleParameters.from_profile(vehicle_profile),
            avoid_tolls=self._costs.policy.avoid_tolls,
            avoid_unpaved=self._costs.policy.avoid_unpaved,
            alternatives=self._costs.policy.alternatives_count,
            traffic_enabled=self._costs.policy.traffic_enabled,
        )
        estimate = await self.estimate(
            cargo.loading_region,
            cargo.unloading_region,
            trace_id=trace_id,
            request=request,
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

    def _remember(self, key: str, estimate: RouteEstimate) -> None:
        if len(self._cache) >= self._cache_limit:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = estimate

    @staticmethod
    def _memory_key(request: RouteRequest) -> str:
        vehicle = request.vehicle
        return "|".join(
            (
                request.origin,
                request.destination,
                str(vehicle.actual_weight_tons) if vehicle else "",
                str(vehicle.max_weight_tons) if vehicle else "",
                str(vehicle.height_m) if vehicle else "",
                str(vehicle.width_m) if vehicle else "",
                str(vehicle.length_m) if vehicle else "",
                str(request.avoid_tolls),
                str(request.avoid_unpaved),
            )
        )

    def _prepare_request(self, request: RouteRequest) -> RouteRequest:
        return RouteRequest(
            origin=request.origin,
            destination=request.destination,
            origin_point=request.origin_point,
            destination_point=request.destination_point,
            vehicle=request.vehicle,
            departure_at=request.departure_at,
            avoid_tolls=request.avoid_tolls or self._costs.policy.avoid_tolls,
            avoid_unpaved=request.avoid_unpaved or self._costs.policy.avoid_unpaved,
            alternatives=(
                request.alternatives
                if request.alternatives != 1
                else self._costs.policy.alternatives_count
            ),
            traffic_enabled=request.traffic_enabled and self._costs.policy.traffic_enabled,
        )
