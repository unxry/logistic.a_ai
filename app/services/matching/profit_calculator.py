"""CargoProfitCalculator — реальная экономика рейса (деньги — Decimal).

Stage 8.5: real_profit = доход − топливо − платные − холостой подгон −
водитель − обслуживание. Стоимости приходят готовыми в RouteEstimate
(их считает RouteCostCalculator по политике из настроек); обслуживание —
сверх формулы ТЗ, это реальные деньги (не нужно — тариф 0 в настройках).
"""

from __future__ import annotations

from decimal import Decimal

from app.core.models.logistics.cargo import Cargo
from app.core.models.matching import ProfitAnalysis
from app.core.models.routes import RouteEstimate


class CargoProfitCalculator:
    """Анализ прибыли рейса (чистый; маршрут даёт RouteService)."""

    def analyze(
        self,
        cargo: Cargo,
        route: RouteEstimate | None,
        *,
        empty_run_cost: Decimal = Decimal(0),
    ) -> ProfitAnalysis | None:
        """Экономика груза; без цены или маршрута анализ невозможен (``None``)."""
        if cargo.payment_amount is None or route is None or route.distance_km <= 0:
            return None
        gross = cargo.payment_amount
        expenses = route.total_cost + empty_run_cost
        net = gross - expenses
        profit_per_km = net / Decimal(str(route.distance_km))
        profit_per_hour = (
            net / Decimal(str(route.duration_hours)) if route.duration_hours > 0 else None
        )
        return ProfitAnalysis(
            gross_profit=gross,
            fuel_cost=route.fuel_cost,
            toll_cost=route.toll_cost,
            driver_cost=route.driver_cost,
            maintenance_cost=route.maintenance_cost,
            empty_run_cost=empty_run_cost,
            expenses=expenses,
            net_profit=net,
            profit_per_km=profit_per_km,
            profit_per_hour=profit_per_hour,
        )
