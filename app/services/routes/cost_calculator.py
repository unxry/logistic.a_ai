"""RouteCostCalculator — деньги маршрута по политике пользователя (без I/O).

Формула ТЗ: ``fuel_cost = distance_km / fuel_consumption(км/л) × fuel_price``.
Реализована в эквивалентной точной форме «литры × цена»
(``distance × расход_л/100км / 100 × цена``) — Decimal без накопления
погрешности деления. total_trip_cost = топливо + платные + водитель +
обслуживание; все тарифы — RouteCostPolicy из настроек.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.core.models.routes import SYNTHETIC_CONFIDENCE, RouteCostPolicy, RouteEstimate


class RouteCostCalculator:
    """Расчёт стоимости рейса и холостого прогона."""

    def __init__(self, policy: RouteCostPolicy | None = None) -> None:
        self._policy = policy if policy is not None else RouteCostPolicy()

    @property
    def policy(self) -> RouteCostPolicy:
        """Действующая политика тарифов."""
        return self._policy

    def fuel_cost(self, distance_km: float) -> Decimal:
        """Топливо: литры × цена (эквивалент формулы ТЗ через км/л)."""
        liters = Decimal(str(distance_km)) * self._policy.fuel_consumption_l_per_100km
        return liters / Decimal(100) * self._policy.fuel_price_per_liter

    def toll_cost(self, distance_km: float) -> Decimal:
        """Платные дороги по усреднённому тарифу за километр."""
        return Decimal(str(distance_km)) * self._policy.toll_cost_per_km

    def maintenance_cost(self, distance_km: float) -> Decimal:
        """Обслуживание и износ (ТО, резина, амортизация)."""
        return Decimal(str(distance_km)) * self._policy.maintenance_cost_per_km

    def driver_cost(self, duration_hours: float) -> Decimal:
        """Оплата водителя за время в пути."""
        return Decimal(str(duration_hours)) * self._policy.driver_cost_per_hour

    def trip_cost(self, distance_km: float, duration_hours: float) -> Decimal:
        """total_trip_cost = топливо + платные + водитель + обслуживание."""
        return (
            self.fuel_cost(distance_km)
            + self.toll_cost(distance_km)
            + self.driver_cost(duration_hours)
            + self.maintenance_cost(distance_km)
        )

    def empty_run_cost(self, distance_km: float) -> Decimal:
        """Холостой подгон: топливо + износ (без платных и ставки водителя)."""
        return self.fuel_cost(distance_km) + self.maintenance_cost(distance_km)

    def enrich(self, estimate: RouteEstimate) -> RouteEstimate:
        """Заполнить деньги в геометрической оценке провайдера.

        Платные: стоимость от провайдера (если он её знает, > 0) точнее
        усреднённого тарифа за километр — тогда она сохраняется.
        """
        fuel = self.fuel_cost(estimate.distance_km)
        toll = (
            estimate.toll_cost if estimate.toll_cost > 0 else self.toll_cost(estimate.distance_km)
        )
        driver = self.driver_cost(estimate.duration_hours)
        maintenance = self.maintenance_cost(estimate.distance_km)
        return replace(
            estimate,
            fuel_cost=fuel,
            toll_cost=toll,
            driver_cost=driver,
            maintenance_cost=maintenance,
            total_cost=fuel + toll + driver + maintenance,
        )

    def synthetic_estimate(self, distance_km: float) -> RouteEstimate:
        """Оценка без провайдера: время по средней скорости, низкая уверенность."""
        duration_hours = distance_km / self._policy.average_speed_kmh
        return self.enrich(
            RouteEstimate(
                distance_km=distance_km,
                duration_hours=duration_hours,
                confidence_score=SYNTHETIC_CONFIDENCE,
            )
        )
