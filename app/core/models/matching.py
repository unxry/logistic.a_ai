"""Модели интеллектуального подбора: контекст, экономика рейса, решение.

Stage 8.5: ProfitAnalysis вместо грубого ProfitEstimate (полная разбивка
расходов, прибыль на километр и на час), веса дополнены свежестью,
контекст несёт оценку маршрута, решение — фактическую дистанцию.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.routes import RouteEstimate
from app.core.models.search import CargoMatch

_WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class MatchingContext:
    """Контекст всех расчётов подбора: машина, водитель, где мы сейчас.

    ``route_estimate`` — оценка маршрута ОДНОГО оцениваемого груза: задаётся
    вызывающим при точечной оценке; при ранжировании сервис подставляет её
    для каждого груза сам (``dataclasses.replace``).
    """

    vehicle_profile: VehicleProfile
    driver_profile: DriverProfile
    current_location: str = ""
    route_estimate: RouteEstimate | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ProfitAnalysis:
    """Экономика рейса (все деньги — Decimal).

    real_profit = доход − топливо − платные − холостой подгон − водитель −
    обслуживание. ``profit_per_hour`` отсутствует, если время в пути неизвестно.
    """

    gross_profit: Decimal
    fuel_cost: Decimal
    toll_cost: Decimal
    driver_cost: Decimal
    maintenance_cost: Decimal
    empty_run_cost: Decimal
    expenses: Decimal
    net_profit: Decimal
    profit_per_km: Decimal | None = None
    profit_per_hour: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MatchingWeights:
    """Веса итоговой оценки подбора (сумма = 1.0, проверяется при создании)."""

    compatibility: float = 0.30
    profit: float = 0.30
    route: float = 0.20
    preferences: float = 0.10
    freshness: float = 0.10

    def __post_init__(self) -> None:
        """Отрицательный вес или сумма ≠ 1.0 — ошибка конфигурации."""
        components = (
            self.compatibility,
            self.profit,
            self.route,
            self.preferences,
            self.freshness,
        )
        if any(weight < 0 for weight in components):
            raise ValueError("Вес компонента подбора не может быть отрицательным")
        if abs(sum(components) - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"Сумма весов подбора должна быть 1.0, получено {sum(components)}")


@dataclass(frozen=True, slots=True)
class IntelligentCargoMatch:
    """Результат интеллектуального подбора с объяснением причин."""

    cargo_match: CargoMatch
    final_score: int
    preference_score: int
    profit_score: int
    route_score: int
    freshness_score: int = 0
    profit: ProfitAnalysis | None = None
    route_estimate: RouteEstimate | None = None
    explanation: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchingDecision:
    """История решения подбора — база для будущего обучения (без ML)."""

    id: str
    cargo_id: str
    driver_id: str
    score: int
    selected: bool
    rejected_reason: str = ""
    vehicle_profile_id: str = ""
    profit: Decimal | None = None
    explanation: tuple[str, ...] = ()
    route: str = ""
    distance_km: float | None = None
    trace_id: str = ""
    timestamp: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        cargo_id: str,
        driver_id: str,
        score: int,
        selected: bool,
        rejected_reason: str = "",
        vehicle_profile_id: str = "",
        profit: Decimal | None = None,
        explanation: tuple[str, ...] = (),
        route: str = "",
        distance_km: float | None = None,
        trace_id: str = "",
    ) -> MatchingDecision:
        """Создать запись решения с новым id."""
        return cls(
            id=uuid4().hex,
            cargo_id=cargo_id,
            driver_id=driver_id,
            score=score,
            selected=selected,
            rejected_reason=rejected_reason,
            vehicle_profile_id=vehicle_profile_id,
            profit=profit,
            explanation=explanation,
            route=route,
            distance_km=distance_km,
            trace_id=trace_id,
        )
