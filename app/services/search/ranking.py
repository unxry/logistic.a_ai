"""CargoRankingService — сортировка результатов подбора.

Порядок: совместимые первыми → score по убыванию → цена по убыванию →
свежие первыми. Позиции проставляются с 1.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.core.models.search import CargoMatch

_NO_PRICE = Decimal(-1)


class CargoRankingService:
    """Ранжирование совпадений."""

    def rank(self, matches: tuple[CargoMatch, ...]) -> tuple[CargoMatch, ...]:
        """Отсортировать и проставить ranking_position (1-based)."""
        ordered = sorted(matches, key=self._sort_key)
        return tuple(
            replace(match, ranking_position=position)
            for position, match in enumerate(ordered, start=1)
        )

    @staticmethod
    def _sort_key(match: CargoMatch) -> tuple[int, int, Decimal, float]:
        price = match.cargo.payment_amount
        return (
            0 if match.compatible else 1,
            -match.score,
            -(price if price is not None else _NO_PRICE),
            -match.cargo.created_at.timestamp(),
        )
