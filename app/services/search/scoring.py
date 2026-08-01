"""CargoScoreCalculator — оценка привлекательности груза (0–100).

Формула v1 (веса настраиваемы через ScoringWeights):
40% совместимость · 20% ставка (руб/км против эталона) · 20% расстояние ·
10% свежесть · 10% категория. Несовместимый груз — всегда 0.
Деньги — Decimal; эвристики зафиксированы тестами и заменяемы целиком
(класс инжектится в движок).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.clock import utc_now
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import CompatibilityResult
from app.core.models.scoring import freshness_score
from app.core.models.search import CargoSearchQuery

# Эталонная ставка: 150 руб/км и выше — максимум баллов за цену (v1).
_EXCELLENT_RATE_RUB_PER_KM = Decimal(150)
# Расстояние: каждый километр съедает 1/20 балла (2000 км → 0).
_DISTANCE_PENALTY_KM_PER_POINT = 20.0
_NEUTRAL = 50.0


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Веса компонентов итоговой оценки (сумма = 1.0)."""

    compatibility: float = 0.40
    price: float = 0.20
    distance: float = 0.20
    freshness: float = 0.10
    category: float = 0.10


class CargoScoreCalculator:
    """Расчёт итогового балла груза."""

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._weights = weights if weights is not None else ScoringWeights()
        self._clock = clock

    def score(
        self,
        cargo: Cargo,
        compatibility: CompatibilityResult,
        query: CargoSearchQuery,
    ) -> int:
        """Итоговый балл 0–100; несовместимый груз — 0."""
        if not compatibility.compatible:
            return 0
        weights = self._weights
        total = (
            compatibility.score * weights.compatibility
            + self._price_score(cargo) * weights.price
            + self._distance_score(cargo) * weights.distance
            + self._freshness_score(cargo) * weights.freshness
            + self._category_score(cargo, query) * weights.category
        )
        return max(0, min(100, round(total)))

    @staticmethod
    def _price_score(cargo: Cargo) -> float:
        """Ставка руб/км против эталона; нет данных — нейтрально."""
        if cargo.payment_amount is None:
            return 0.0
        if cargo.distance_km is None or cargo.distance_km <= 0:
            return _NEUTRAL
        rate = cargo.payment_amount / Decimal(str(cargo.distance_km))
        return min(100.0, float(rate / _EXCELLENT_RATE_RUB_PER_KM * 100))

    @staticmethod
    def _distance_score(cargo: Cargo) -> float:
        """Короче плечо — выше балл (меньше издержек); нет данных — нейтрально."""
        if cargo.distance_km is None:
            return _NEUTRAL
        return max(0.0, 100.0 - cargo.distance_km / _DISTANCE_PENALTY_KM_PER_POINT)

    def _freshness_score(self, cargo: Cargo) -> float:
        """Свежий заказ ценнее (общая кривая ядра: 100 сейчас → 0 через сутки)."""
        return freshness_score(cargo.created_at, self._clock())

    @staticmethod
    def _category_score(cargo: Cargo, query: CargoSearchQuery) -> float:
        """Совпадение с категориями запроса; запрос без категорий — нейтрально."""
        if not query.categories:
            return _NEUTRAL
        return 100.0 if cargo.category in query.categories else 0.0
