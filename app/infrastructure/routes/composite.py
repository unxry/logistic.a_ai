"""CompositeRouteProvider: Yandex → OSRM → stale cache → Mock."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from app.core.clock import utc_now
from app.core.errors import RouteError
from app.core.events import (
    Event,
    RouteCacheHit,
    RouteCacheMiss,
    RouteCalculationFailed,
    RouteFallbackUsed,
    RouteProviderSelected,
)
from app.core.models.routes import (
    RouteCachePolicy,
    RouteEstimate,
    RouteProviderChoice,
    RouteRequest,
)
from app.core.ports import EventPublisher, GeocodingProvider, RouteCacheRepository, RouteProvider


class CompositeRouteProvider:
    """Production provider chain with cache and fallback observability."""

    provider_id = "composite"

    def __init__(
        self,
        *,
        yandex: RouteProvider | None,
        osrm: RouteProvider | None,
        mock: RouteProvider | None,
        geocoder: GeocodingProvider,
        cache: RouteCacheRepository | None,
        events: EventPublisher | None = None,
        cache_policy: RouteCachePolicy | None = None,
        provider_choice: RouteProviderChoice = RouteProviderChoice.AUTO,
        cache_enabled: bool = True,
        fallback_enabled: bool = True,
    ) -> None:
        self._yandex = yandex
        self._osrm = osrm
        self._mock = mock
        self._geocoder = geocoder
        self._cache = cache
        self._events = events
        self._policy = cache_policy if cache_policy is not None else RouteCachePolicy()
        self._provider_choice = provider_choice
        self._cache_enabled = cache_enabled
        self._fallback_enabled = fallback_enabled
        self._locks: dict[str, asyncio.Lock] = {}

    async def calculate_route(
        self,
        origin: str,
        destination: str,
        *,
        request: RouteRequest | None = None,
    ) -> RouteEstimate | None:
        """Try configured provider chain."""
        base_request = request if request is not None else RouteRequest.simple(origin, destination)
        route_request = await self._with_points(base_request)
        providers = self._providers()
        last_error = ""
        for index, (provider_id, provider) in enumerate(providers):
            if provider is None:
                continue
            self._publish(
                RouteProviderSelected(
                    provider=provider_id,
                    origin=origin,
                    destination=destination,
                )
            )
            key = self._cache_key(route_request, provider_id)
            cached = await self._fresh_cache(provider_id, key)
            if cached is not None:
                return cached
            lock = self._lock(key)
            async with lock:
                cached = await self._fresh_cache(provider_id, key)
                if cached is not None:
                    return cached
                try:
                    estimate = await provider.calculate_route(
                        origin,
                        destination,
                        request=route_request,
                    )
                except RouteError as exc:
                    last_error = str(exc)
                    self._publish(
                        RouteCalculationFailed(
                            provider=provider_id,
                            origin=origin,
                            destination=destination,
                            error=type(exc).__name__,
                        )
                    )
                    if not self._fallback_enabled:
                        return None
                    self._publish_fallback(provider_id, providers, index, last_error)
                    continue
                if estimate is None:
                    last_error = "empty result"
                    if not self._fallback_enabled:
                        return None
                    self._publish_fallback(provider_id, providers, index, last_error)
                    continue
                if index > 0 or estimate.is_fallback:
                    estimate = _fallback_estimate(
                        estimate,
                        reason=f"Fallback after {providers[0][0]} failure",
                    )
                await self._save_cache(key, estimate)
                return estimate
        stale = await self._stale_cache(route_request, providers)
        if stale is not None:
            return _fallback_estimate(stale, reason="Использован устаревший кэш маршрута")
        return None

    async def _with_points(self, request: RouteRequest) -> RouteRequest:
        origin_point = request.origin_point or await self._geocoder.geocode(request.origin)
        destination_point = request.destination_point or await self._geocoder.geocode(
            request.destination
        )
        return replace(request, origin_point=origin_point, destination_point=destination_point)

    def _providers(self) -> tuple[tuple[str, RouteProvider | None], ...]:
        if self._provider_choice is RouteProviderChoice.YANDEX:
            return (("yandex", self._yandex), ("osrm", self._osrm), ("mock", self._mock))
        if self._provider_choice is RouteProviderChoice.OSRM:
            return (("osrm", self._osrm), ("mock", self._mock))
        if self._provider_choice is RouteProviderChoice.MOCK:
            return (("mock", self._mock),)
        return (("yandex", self._yandex), ("osrm", self._osrm), ("mock", self._mock))

    async def _fresh_cache(self, provider_id: str, key: str) -> RouteEstimate | None:
        if self._cache is None or not self._cache_enabled:
            return None
        now = utc_now()
        cached = await self._cache.get_route(key, now=now)
        if cached is not None:
            self._publish(RouteCacheHit(provider=provider_id, cache_key=key))
            return cached
        self._publish(RouteCacheMiss(provider=provider_id, cache_key=key))
        return None

    async def _save_cache(self, key: str, estimate: RouteEstimate) -> None:
        if self._cache is None or not self._cache_enabled:
            return
        await self._cache.save_route(
            key,
            estimate,
            ttl=self._policy.route_ttl(
                provider=estimate.provider,
                traffic_aware=estimate.traffic_aware,
            ),
        )

    async def _stale_cache(
        self,
        request: RouteRequest,
        providers: tuple[tuple[str, RouteProvider | None], ...],
    ) -> RouteEstimate | None:
        if self._cache is None or not self._cache_enabled:
            return None
        for provider_id, _provider in providers:
            cached = await self._cache.get_stale_route(self._cache_key(request, provider_id))
            if cached is not None:
                self._publish(RouteCacheHit(provider=provider_id, cache_key="stale"))
                return cached
        return None

    def _cache_key(self, request: RouteRequest, provider: str) -> str:
        if self._cache is None:
            return f"{provider}:{request.origin}:{request.destination}"
        return self._cache.route_key(request, provider=provider)

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _publish_fallback(
        self,
        provider_id: str,
        providers: tuple[tuple[str, RouteProvider | None], ...],
        index: int,
        reason: str,
    ) -> None:
        if index + 1 >= len(providers):
            return
        self._publish(
            RouteFallbackUsed(
                from_provider=provider_id,
                to_provider=providers[index + 1][0],
                reason=reason,
            )
        )

    def _publish(self, event: Event) -> None:
        if self._events is not None:
            self._events.publish(event)


def _fallback_estimate(estimate: RouteEstimate, *, reason: str) -> RouteEstimate:
    warnings = (
        (*estimate.warnings, reason) if reason not in estimate.warnings else estimate.warnings
    )
    return replace(estimate, is_fallback=True, warnings=warnings)
