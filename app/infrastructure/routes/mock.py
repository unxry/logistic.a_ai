"""MockRouteProvider — детерминированные маршруты для тестов и dev-режима.

Реальные провайдеры (OSRM, Яндекс Карты, Google Maps, HERE) встанут за тот же
порт RouteProvider без изменения сервисов. До их появления таблица основных
направлений делает подбор осмысленным, а незнакомое направление честно
возвращает ``None`` — RouteService перейдёт на синтетическую оценку.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.models.routes import PROVIDER_CONFIDENCE, RouteEstimate, RouteRequest

# (откуда, куда) → (километры, часы); поиск симметричный.
_DEFAULT_ROUTES: dict[tuple[str, str], tuple[float, float]] = {
    ("Москва", "Санкт-Петербург"): (710.0, 10.0),
    ("Москва", "Казань"): (820.0, 11.5),
    ("Москва", "Нижний Новгород"): (420.0, 6.0),
    ("Москва", "Воронеж"): (520.0, 7.5),
    ("Москва", "Тверь"): (170.0, 2.5),
    ("Санкт-Петербург", "Великий Новгород"): (190.0, 2.8),
}


class MockRouteProvider:
    """Реализация порта RouteProvider на статической таблице направлений."""

    def __init__(
        self,
        routes: Mapping[tuple[str, str], tuple[float, float]] | None = None,
        *,
        confidence_score: int = PROVIDER_CONFIDENCE,
    ) -> None:
        self._routes = dict(routes) if routes is not None else dict(_DEFAULT_ROUTES)
        self._confidence = confidence_score
        self.calls = 0  # наблюдаемость для тестов кэширования

    async def calculate_route(
        self,
        origin: str,
        destination: str,
        *,
        request: RouteRequest | None = None,
    ) -> RouteEstimate | None:
        """Геометрия направления; ``None`` — направления нет в таблице."""
        self.calls += 1
        if not origin or not destination:
            return None
        if origin == destination:
            return RouteEstimate(
                distance_km=0.0,
                duration_hours=0.0,
                confidence_score=100,
                provider="mock",
                provider_label="Mock",
            )
        leg = self._routes.get((origin, destination)) or self._routes.get((destination, origin))
        if leg is None:
            return None
        distance_km, duration_hours = leg
        return RouteEstimate(
            distance_km=distance_km,
            duration_hours=duration_hours,
            confidence_score=self._confidence,
            provider="mock",
            provider_label="Mock",
            warnings=("Mock route provider: dev/offline estimate",),
        )
