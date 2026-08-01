"""Порт хранилища решений подбора (база будущего обучения и аналитики)."""

from __future__ import annotations

from typing import Protocol

from app.core.models.analytics import DriverAnalytics, MatchingAnalytics, RouteAnalytics
from app.core.models.matching import MatchingDecision


class MatchingRepository(Protocol):
    """Хранение и агрегация решений (SQLite)."""

    async def save_decision(self, decision: MatchingDecision) -> None:
        """Сохранить решение."""
        ...

    async def get_history(
        self, *, driver_id: str | None = None, limit: int = 100
    ) -> tuple[MatchingDecision, ...]:
        """История решений (новые первыми)."""
        ...

    async def get_statistics(self) -> MatchingAnalytics:
        """Сводная статистика подбора."""
        ...

    async def route_statistics(self) -> RouteAnalytics:
        """Маршрутная аналитика: дистанции, прибыль на километр, лучшие/худшие."""
        ...

    async def driver_statistics(self, driver_id: str) -> DriverAnalytics:
        """Метрики конкретного водителя."""
        ...
