"""RouteScoreCalculator — эффективность маршрута (Stage 8.5).

Региональные эвристики v1 (подача у дома или рядом, возврат домой) дополнены
факторами реальной оценки RouteEstimate: скорость трассы, доля платных дорог,
приблизительность данных. Точные расстояния приходят из MatchingContext —
провайдеры карт меняются за портом, этот класс остаётся.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.models.logistics.cargo import Cargo
from app.core.models.matching import MatchingContext

_BASE = 50
_HOME_PICKUP_BONUS = 50
_NEARBY_PICKUP_BONUS = 40
_RETURN_HOME_BONUS = 10
_FAST_ROAD_BONUS = 10
_TOLL_SHARE_PENALTY = 10
# Средняя скорость магистрали: быстрее — меньше часов на километр дохода.
_FAST_SPEED_KMH = 65.0
# Платные дороги дороже четверти расходов — маршрут «съедает» прибыль.
_TOLL_SHARE_LIMIT = Decimal("0.25")


class RouteScoreCalculator:
    """Оценка эффективности маршрута 0–100."""

    def score(self, cargo: Cargo, context: MatchingContext) -> tuple[int, tuple[str, ...]]:
        """(балл, пояснения)."""
        score = _BASE
        notes: list[str] = []
        home = context.driver_profile.home_region
        location = context.current_location

        if home and cargo.loading_region == home:
            score += _HOME_PICKUP_BONUS
            notes.append("Минимальный холостой пробег: загрузка в домашнем регионе")
        elif location and cargo.loading_region == location:
            score += _NEARBY_PICKUP_BONUS
            notes.append("Загрузка рядом с текущим местоположением")
        if home and cargo.unloading_region == home:
            score += _RETURN_HOME_BONUS
            notes.append("Выгрузка ведёт домой")

        estimate = context.route_estimate
        if estimate is not None and estimate.distance_km > 0:
            if (
                estimate.duration_hours > 0
                and estimate.distance_km / estimate.duration_hours >= _FAST_SPEED_KMH
            ):
                score += _FAST_ROAD_BONUS
                notes.append("Быстрая магистральная трасса")
            if (
                estimate.total_cost > 0
                and estimate.toll_cost / estimate.total_cost > _TOLL_SHARE_LIMIT
            ):
                score -= _TOLL_SHARE_PENALTY
                notes.append("Высокая доля платных дорог")
            if estimate.confidence_score < 50:
                score -= 5
                notes.append("Маршрут оценён приблизительно")
            if estimate.provider_label:
                notes.append(f"Провайдер маршрута: {estimate.provider_label}")
            if estimate.traffic_duration_hours is not None:
                notes.append(f"Время с трафиком: {estimate.traffic_duration_hours:.1f} ч")
            if estimate.has_tolls is True:
                notes.append("Платные дороги: есть")
            if estimate.warnings:
                notes.extend(estimate.warnings[:2])
        return max(0, min(100, score)), tuple(notes)
