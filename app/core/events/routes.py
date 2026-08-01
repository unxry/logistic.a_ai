"""События маршрутной аналитики (Stage 8.5)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.matching import ProfitAnalysis
from app.core.models.routes import Route


@dataclass(frozen=True, slots=True)
class RouteCalculated(Event):
    """Маршрут рассчитан провайдером (попадание в кэш повторно не публикуется)."""

    route: Route
    trace_id: str = ""
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class ProfitCalculated(Event):
    """Экономика груза рассчитана."""

    cargo_id: str
    analysis: ProfitAnalysis
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class RouteProviderSelected(Event):
    """Выбран route provider для расчёта."""

    provider: str
    origin: str
    destination: str
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class RouteCacheHit(Event):
    """Маршрут найден в persistent cache."""

    provider: str
    cache_key: str
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class RouteCacheMiss(Event):
    """Маршрут отсутствует в persistent cache."""

    provider: str
    cache_key: str
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class RouteFallbackUsed(Event):
    """Расчёт маршрута деградировал на fallback provider/cache/mock."""

    from_provider: str
    to_provider: str
    reason: str
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class RouteCalculationFailed(Event):
    """Провайдер маршрутов не смог рассчитать маршрут."""

    provider: str
    origin: str
    destination: str
    error: str
    trace_id: str = ""
