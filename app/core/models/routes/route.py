"""Доменные модели маршрутов (Stage 8.5).

Деньги — Decimal, физика (километры, часы) — float. Провайдер карт знает
только геометрию (расстояние, время, уверенность, иногда платные участки);
деньги досчитывает RouteCostCalculator по политике пользователя — поэтому
денежные поля оценки имеют дефолт 0 и уточняются через ``dataclasses.replace``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.clock import utc_now

#: Уверенность провайдера карт (точный маршрут по дорогам).
PROVIDER_CONFIDENCE = 90
#: Уверенность синтетической оценки (расстояние из объявления, время по средней скорости).
SYNTHETIC_CONFIDENCE = 40


@dataclass(frozen=True, slots=True)
class RouteEstimate:
    """Оценка маршрута: геометрия провайдера + стоимости по политике.

    ``confidence_score`` 0–100: 100 — тривиальный маршрут (точка совпадает),
    ~90 — провайдер карт, ~40 — синтетическая оценка по объявлению.
    """

    distance_km: float
    duration_hours: float
    fuel_cost: Decimal = Decimal(0)
    toll_cost: Decimal = Decimal(0)
    driver_cost: Decimal = Decimal(0)
    maintenance_cost: Decimal = Decimal(0)
    total_cost: Decimal = Decimal(0)
    confidence_score: int = PROVIDER_CONFIDENCE


@dataclass(frozen=True, slots=True)
class Route:
    """Рассчитанный маршрут — запись факта (события, аналитика, будущий кэш)."""

    id: str
    from_location: str
    to_location: str
    distance_km: float
    estimated_hours: float
    toll_cost: Decimal
    fuel_cost: Decimal
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, from_location: str, to_location: str, estimate: RouteEstimate) -> Route:
        """Собрать запись маршрута из готовой оценки."""
        return cls(
            id=uuid4().hex,
            from_location=from_location,
            to_location=to_location,
            distance_km=estimate.distance_km,
            estimated_hours=estimate.duration_hours,
            toll_cost=estimate.toll_cost,
            fuel_cost=estimate.fuel_cost,
        )
