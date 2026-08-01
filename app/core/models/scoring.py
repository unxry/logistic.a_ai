"""Общие чистые функции скоринга (используются поиском и подбором)."""

from __future__ import annotations

from datetime import datetime

#: Свежесть: заказ старше суток — 0 баллов за свежесть (v1).
FRESHNESS_WINDOW_HOURS = 24.0


def freshness_score(
    created_at: datetime,
    now: datetime,
    window_hours: float = FRESHNESS_WINDOW_HOURS,
) -> float:
    """Свежий заказ ценнее: линейно от 100 (сейчас) до 0 (окно истекло)."""
    age_hours = (now - created_at).total_seconds() / 3600
    return max(0.0, 100.0 * (1.0 - age_hours / window_hours))
