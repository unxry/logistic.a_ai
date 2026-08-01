"""Порт геокодирования локаций в координаты."""

from __future__ import annotations

from typing import Protocol

from app.core.models.routes import GeoPoint


class GeocodingProvider(Protocol):
    """Геокодер строковых регионов/городов."""

    async def geocode(self, location: str) -> GeoPoint | None:
        """Вернуть координаты или None, если место неизвестно."""
        ...
