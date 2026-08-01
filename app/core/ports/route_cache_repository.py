"""Порт persistent cache для маршрутов и геокодинга."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from app.core.models.routes import GeoPoint, RouteEstimate, RouteRequest


class RouteCacheRepository(Protocol):
    """SQLite-ready кэш маршрутов и геокодинга."""

    async def get_route(self, key: str, *, now: datetime) -> RouteEstimate | None:
        """Маршрут из кэша, если не истёк TTL."""
        ...

    async def get_stale_route(self, key: str) -> RouteEstimate | None:
        """Последний маршрут даже после TTL — только для аварийного fallback."""
        ...

    async def save_route(self, key: str, estimate: RouteEstimate, *, ttl: timedelta) -> None:
        """Сохранить маршрут с TTL."""
        ...

    async def get_geocode(self, location: str, *, now: datetime) -> GeoPoint | None:
        """Геокод из кэша, если не истёк TTL."""
        ...

    async def save_geocode(self, location: str, point: GeoPoint, *, ttl: timedelta) -> None:
        """Сохранить геокод с TTL."""
        ...

    def route_key(self, request: RouteRequest, *, provider: str) -> str:
        """Стабильный ключ маршрута с учётом координат, грузовика и настроек."""
        ...
