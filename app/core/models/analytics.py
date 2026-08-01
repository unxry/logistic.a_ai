"""Модели аналитики: источники, подбор, водитель, маршруты (Stage 8/8.5)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.models.matching import MatchingDecision


@dataclass(frozen=True, slots=True)
class SourceAnalytics:
    """Статистика источника за период."""

    source_id: str
    period: str = "all"
    total_received: int = 0
    normalized_count: int = 0
    duplicate_count: int = 0  # дедупликация появится в Stage 9
    failed_count: int = 0
    average_response_time_ms: float = 0.0
    last_success: datetime | None = None


@dataclass(frozen=True, slots=True)
class MatchingAnalytics:
    """Статистика подбора грузов."""

    total_matches: int = 0
    compatible_count: int = 0
    rejected_count: int = 0
    average_score: float = 0.0
    average_profit: Decimal = Decimal(0)
    best_routes: tuple[str, ...] = ()
    rejection_reasons: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutePerformance:
    """Экономика одного направления по накопленным решениям."""

    route: str
    decision_count: int
    average_profit: Decimal
    average_profit_per_km: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RouteAnalytics:
    """Маршрутная аналитика по выбранным грузам (Stage 8.5).

    С малым числом направлений best и worst могут пересекаться —
    потребитель показывает то, что осмысленно.
    """

    routes_count: int = 0
    average_distance_km: float = 0.0
    average_profit_per_km: Decimal = Decimal(0)
    best_routes: tuple[RoutePerformance, ...] = ()
    worst_routes: tuple[RoutePerformance, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverAnalytics:
    """Метрики водителя."""

    driver_id: str
    searched_count: int = 0
    selected_count: int = 0
    rejected_count: int = 0
    estimated_income: Decimal = Decimal(0)
    average_match_score: float = 0.0


def summarize_decisions(decisions: Sequence[MatchingDecision]) -> MatchingAnalytics:
    """Чистая агрегация решений подбора (используется и сервисом, и хранилищем)."""
    from collections import Counter

    if not decisions:
        return MatchingAnalytics()
    selected = [d for d in decisions if d.selected]
    rejected = [d for d in decisions if not d.selected]
    profits = [d.profit for d in selected if d.profit is not None]
    reasons = Counter(d.rejected_reason for d in rejected if d.rejected_reason)
    routes = Counter(d.route for d in selected if d.route)
    return MatchingAnalytics(
        total_matches=len(decisions),
        compatible_count=len(selected),
        rejected_count=len(rejected),
        average_score=sum(d.score for d in decisions) / len(decisions),
        average_profit=(sum(profits, start=Decimal(0)) / len(profits) if profits else Decimal(0)),
        best_routes=tuple(route for route, _ in routes.most_common(3)),
        rejection_reasons=dict(reasons.most_common()),
    )


def _profit_per_km(decision: MatchingDecision) -> Decimal | None:
    if decision.profit is None or decision.distance_km is None or decision.distance_km <= 0:
        return None
    return decision.profit / Decimal(str(decision.distance_km))


def summarize_routes(decisions: Sequence[MatchingDecision], *, top: int = 3) -> RouteAnalytics:
    """Чистая маршрутная агрегация выбранных решений (прибыль и дистанция).

    Направления ранжируются по средней чистой прибыли; переиспользуется
    и сервисом качества, и SQLite-хранилищем.
    """
    selected = [d for d in decisions if d.selected and d.route and d.profit is not None]
    if not selected:
        return RouteAnalytics()

    by_route: dict[str, list[MatchingDecision]] = {}
    for decision in selected:
        by_route.setdefault(decision.route, []).append(decision)

    performances: list[RoutePerformance] = []
    for route, items in by_route.items():
        profits = [d.profit for d in items if d.profit is not None]
        rates = [rate for rate in (_profit_per_km(d) for d in items) if rate is not None]
        performances.append(
            RoutePerformance(
                route=route,
                decision_count=len(items),
                average_profit=sum(profits, start=Decimal(0)) / len(profits),
                average_profit_per_km=(
                    sum(rates, start=Decimal(0)) / len(rates) if rates else None
                ),
            )
        )
    ranked = sorted(performances, key=lambda p: p.average_profit, reverse=True)

    distances = [d.distance_km for d in selected if d.distance_km is not None and d.distance_km > 0]
    all_rates = [rate for rate in (_profit_per_km(d) for d in selected) if rate is not None]
    return RouteAnalytics(
        routes_count=len(ranked),
        average_distance_km=sum(distances) / len(distances) if distances else 0.0,
        average_profit_per_km=(
            sum(all_rates, start=Decimal(0)) / len(all_rates) if all_rates else Decimal(0)
        ),
        best_routes=tuple(ranked[:top]),
        worst_routes=tuple(ranked[::-1][:top]),
    )
