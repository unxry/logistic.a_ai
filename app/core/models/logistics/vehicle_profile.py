"""Профиль транспорта пользователя — центральная модель домена.

Главная ценность продукта: «найди груз, который подходит именно моему
автомобилю». Профиль описывает возможности машины; совместимость с грузом
считает ``BasicCompatibilityChecker`` (см. ``compatibility.py``).

Профиль — данные, а не поведение: разные типы автомобилей описываются
значениями полей, а не подклассами (ADR-0009).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.core.clock import utc_now


class VehicleType(Enum):
    """Тип транспортного средства."""

    TRUCK = "truck"  # среднетоннажный грузовик
    SEMI_TRAILER = "semi_trailer"  # фура / полуприцеп
    VAN = "van"  # малотоннажный фургон
    OTHER = "other"


class BodyType(Enum):
    """Тип кузова."""

    TENT = "tent"  # тент
    REFRIGERATOR = "refrigerator"  # рефрижератор
    ISOTHERMAL = "isothermal"  # изотермический
    BOX = "box"  # цельнометаллический фургон
    FLATBED = "flatbed"  # бортовой
    CONTAINER = "container"  # контейнеровоз
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class VehicleProfile:
    """Профиль автомобиля пользователя.

    ``cargo_capacity_kg`` — грузоподъёмность (payload); именно она участвует
    в проверке совместимости. ``max_weight_kg`` — полная разрешённая масса
    (может быть неизвестна). Габариты — внутренние размеры кузова в см.
    ``allowed_regions`` — регионы работы; пустой кортеж = без ограничений.
    """

    id: str
    name: str
    vehicle_type: VehicleType
    body_type: BodyType
    cargo_capacity_kg: int
    length_cm: int
    width_cm: int
    height_cm: int
    volume_m3: float
    pallet_capacity: int
    created_at: datetime
    updated_at: datetime
    max_weight_kg: int | None = None
    allowed_regions: tuple[str, ...] = ()
    empty_weight_kg: int | None = None
    axle_weight_kg: int | None = None
    vehicle_permits: tuple[str, ...] = ()
    has_trailer: bool = False
    eco_class: int | None = None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        vehicle_type: VehicleType,
        body_type: BodyType,
        cargo_capacity_kg: int,
        length_cm: int,
        width_cm: int,
        height_cm: int,
        volume_m3: float,
        pallet_capacity: int,
        max_weight_kg: int | None = None,
        allowed_regions: tuple[str, ...] = (),
        empty_weight_kg: int | None = None,
        axle_weight_kg: int | None = None,
        vehicle_permits: tuple[str, ...] = (),
        has_trailer: bool = False,
        eco_class: int | None = None,
    ) -> VehicleProfile:
        """Создать профиль с новым id и текущим временем UTC."""
        now = utc_now()
        return cls(
            id=uuid4().hex,
            name=name,
            vehicle_type=vehicle_type,
            body_type=body_type,
            cargo_capacity_kg=cargo_capacity_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            volume_m3=volume_m3,
            pallet_capacity=pallet_capacity,
            created_at=now,
            updated_at=now,
            max_weight_kg=max_weight_kg,
            allowed_regions=allowed_regions,
            empty_weight_kg=empty_weight_kg,
            axle_weight_kg=axle_weight_kg,
            vehicle_permits=vehicle_permits,
            has_trailer=has_trailer,
            eco_class=eco_class,
        )
