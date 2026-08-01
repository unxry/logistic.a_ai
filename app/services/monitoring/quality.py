"""MatchingQualityService — сводка качества подбора.

Отвечает на «почему выбран / почему отвергнут» в цифрах: счётчики,
средний балл, средняя прибыль, топ причин отказов, лучшие и худшие маршруты.
Сама агрегация — чистые функции ядра (summarize_decisions, summarize_routes),
переиспользуемые хранилищем без нарушения контрактов.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.models.analytics import (
    MatchingAnalytics,
    RouteAnalytics,
    summarize_decisions,
    summarize_routes,
)
from app.core.models.matching import MatchingDecision


class MatchingQualityService:
    """Сводка качества подбора (без I/O)."""

    def summarize(self, decisions: Sequence[MatchingDecision]) -> MatchingAnalytics:
        """Агрегировать решения в MatchingAnalytics."""
        return summarize_decisions(decisions)

    def routes(self, decisions: Sequence[MatchingDecision]) -> RouteAnalytics:
        """Маршрутная аналитика: дистанции, ₽/км, лучшие и худшие направления."""
        return summarize_routes(decisions)
