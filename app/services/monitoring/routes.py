"""Route provider observability: metrics + user-facing degradation notices."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Coroutine
from typing import Any

from app.buses import EventBus
from app.core.events import (
    RouteCacheHit,
    RouteCacheMiss,
    RouteCalculated,
    RouteCalculationFailed,
    RouteFallbackUsed,
    RouteProviderSelected,
)
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.severity import Severity
from app.services.notifications import NotificationCooldownPolicy, NotificationService

logger = logging.getLogger(__name__)

_YANDEX_DOWN_KEY = "route-provider:yandex-down"


class RouteMetricsCollector:
    """In-memory метрики route providers из доменных событий."""

    def __init__(self) -> None:
        self.requests_by_provider: Counter[str] = Counter()
        self.failures_by_provider: Counter[str] = Counter()
        self.cache_hits_by_provider: Counter[str] = Counter()
        self.cache_misses_by_provider: Counter[str] = Counter()
        self.fallbacks_by_provider: Counter[str] = Counter()
        self.routes_by_provider: Counter[str] = Counter()
        self.total_latency_ms = 0
        self.latency_samples = 0

    def attach(self, bus: EventBus) -> None:
        """Подписаться на route events."""
        bus.subscribe(RouteProviderSelected, self._on_provider_selected)
        bus.subscribe(RouteCacheHit, self._on_cache_hit)
        bus.subscribe(RouteCacheMiss, self._on_cache_miss)
        bus.subscribe(RouteFallbackUsed, self._on_fallback)
        bus.subscribe(RouteCalculationFailed, self._on_failure)
        bus.subscribe(RouteCalculated, self._on_route_calculated)

    @property
    def average_latency_ms(self) -> float:
        """Средняя latency успешного расчёта маршрута."""
        if self.latency_samples == 0:
            return 0.0
        return self.total_latency_ms / self.latency_samples

    @property
    def cache_hit_rate(self) -> float:
        """Доля route cache hits среди cache lookups."""
        hits = sum(self.cache_hits_by_provider.values())
        misses = sum(self.cache_misses_by_provider.values())
        total = hits + misses
        return hits / total if total else 0.0

    @property
    def fallback_rate(self) -> float:
        """Доля fallback-сценариев среди выбранных providers."""
        requests = sum(self.requests_by_provider.values())
        fallbacks = sum(self.fallbacks_by_provider.values())
        return fallbacks / requests if requests else 0.0

    def snapshot(self) -> dict[str, object]:
        """Снимок для diagnostics/benchmark UI без экспорта mutable Counter."""
        return {
            "average_latency_ms": self.average_latency_ms,
            "cache_hit_rate": self.cache_hit_rate,
            "fallback_rate": self.fallback_rate,
            "failures_by_provider": dict(self.failures_by_provider),
            "requests_by_provider": dict(self.requests_by_provider),
        }

    def _on_provider_selected(self, event: RouteProviderSelected) -> None:
        self.requests_by_provider[event.provider] += 1

    def _on_cache_hit(self, event: RouteCacheHit) -> None:
        self.cache_hits_by_provider[event.provider] += 1

    def _on_cache_miss(self, event: RouteCacheMiss) -> None:
        self.cache_misses_by_provider[event.provider] += 1

    def _on_fallback(self, event: RouteFallbackUsed) -> None:
        self.fallbacks_by_provider[event.from_provider] += 1

    def _on_failure(self, event: RouteCalculationFailed) -> None:
        self.failures_by_provider[event.provider] += 1

    def _on_route_calculated(self, event: RouteCalculated) -> None:
        self.routes_by_provider[event.route.provider] += 1
        if event.latency_ms > 0:
            self.total_latency_ms += event.latency_ms
            self.latency_samples += 1


class RouteAvailabilityNotifier:
    """Оповещает диспетчера о деградации/восстановлении Yandex routes."""

    def __init__(
        self,
        notifications: NotificationService,
        cooldown: NotificationCooldownPolicy | None = None,
    ) -> None:
        self._notifications = notifications
        self._cooldown = cooldown if cooldown is not None else NotificationCooldownPolicy()
        self._yandex_degraded = False
        self._tasks: set[asyncio.Task[None]] = set()

    def attach(self, bus: EventBus) -> None:
        """Подписаться на fallback/recovery events."""
        bus.subscribe(RouteFallbackUsed, self._on_fallback)
        bus.subscribe(RouteCalculated, self._on_route_calculated)

    def _on_fallback(self, event: RouteFallbackUsed) -> None:
        if event.from_provider != "yandex":
            return
        self._yandex_degraded = True
        if not self._cooldown.should_send(_YANDEX_DOWN_KEY):
            return
        self._spawn(self._notify_yandex_down(event.trace_id))

    def _on_route_calculated(self, event: RouteCalculated) -> None:
        if event.route.provider != "yandex" or not self._yandex_degraded:
            return
        self._yandex_degraded = False
        self._cooldown.reset(_YANDEX_DOWN_KEY)
        self._spawn(self._notify_yandex_recovered(event.trace_id))

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            logger.warning("Нет asyncio loop — route availability notification не отправлено")
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _notify_yandex_down(self, trace_id: str) -> None:
        notification = (
            NotificationBuilder()
            .title("⚠️ Yandex Routes недоступен")
            .body("Используется приблизительный маршрут OSRM")
            .severity(Severity.WARNING)
            .category(NotificationCategory.ROUTE)
            .source("routes")
            .module("yandex")
            .trace_id(trace_id)
            .build()
        )
        await self._notifications.send(notification)

    async def _notify_yandex_recovered(self, trace_id: str) -> None:
        notification = (
            NotificationBuilder()
            .title("🟢 Точный грузовой расчёт маршрутов восстановлен")
            .body("Yandex Truck Routing снова отвечает.")
            .severity(Severity.SUCCESS)
            .category(NotificationCategory.ROUTE)
            .source("routes")
            .module("yandex")
            .trace_id(trace_id)
            .build()
        )
        await self._notifications.send(notification)
