"""Порт провайдера маршрутов (OSRM / Яндекс Карты / Google Maps / HERE — позже).

Провайдер знает ГЕОМЕТРИЮ: расстояние, время в пути, уверенность и, если API
её отдаёт, стоимость платных участков. Остальные деньги (топливо, водитель,
обслуживание) досчитывает RouteCostCalculator по политике пользователя —
реализациям порта настройки экономики не нужны.

Интерфейс асинхронный: реальные провайдеры — это HTTP-запросы.
"""

from __future__ import annotations

from typing import Protocol

from app.core.models.routes import RouteEstimate


class RouteProvider(Protocol):
    """Расчёт маршрута между двумя точками (регионы/города)."""

    async def calculate_route(self, origin: str, destination: str) -> RouteEstimate | None:
        """Оценка маршрута; ``None`` — направление провайдеру неизвестно."""
        ...
