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


@dataclass(frozen=True, slots=True)
class ProfitCalculated(Event):
    """Экономика груза рассчитана."""

    cargo_id: str
    analysis: ProfitAnalysis
    trace_id: str = ""
