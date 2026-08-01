"""Профиль предпочтений водителя — доменная модель (не пользователь UI).

Отдельно от VehicleProfile: машина описывает физические возможности,
водитель — коммерческие и маршрутные предпочтения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.vehicle_profile import BodyType


@dataclass(frozen=True, slots=True)
class DriverProfile:
    """Предпочтения водителя (пустое значение = «не важно»)."""

    id: str
    preferred_regions: tuple[str, ...] = ()
    forbidden_regions: tuple[str, ...] = ()
    preferred_cargo_categories: tuple[CargoCategory, ...] = ()
    preferred_body_types: tuple[BodyType, ...] = ()
    minimum_price_per_km: Decimal | None = None
    minimum_profit: Decimal | None = None
    preferred_distance_km: float | None = None
    home_region: str = ""
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        preferred_regions: tuple[str, ...] = (),
        forbidden_regions: tuple[str, ...] = (),
        preferred_cargo_categories: tuple[CargoCategory, ...] = (),
        preferred_body_types: tuple[BodyType, ...] = (),
        minimum_price_per_km: Decimal | None = None,
        minimum_profit: Decimal | None = None,
        preferred_distance_km: float | None = None,
        home_region: str = "",
    ) -> DriverProfile:
        """Создать профиль с новым id."""
        return cls(
            id=uuid4().hex,
            preferred_regions=preferred_regions,
            forbidden_regions=forbidden_regions,
            preferred_cargo_categories=preferred_cargo_categories,
            preferred_body_types=preferred_body_types,
            minimum_price_per_km=minimum_price_per_km,
            minimum_profit=minimum_profit,
            preferred_distance_km=preferred_distance_km,
            home_region=home_region,
        )
