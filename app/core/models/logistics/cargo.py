"""Черновик модели Cargo (DRAFT, API нестабилен).

Контракт для порта ``CargoSource.fetch`` и проверки совместимости.
Физические параметры опциональны: источники часто отдают неполные карточки —
отсутствие данных даёт предупреждение при проверке совместимости, а не отказ.
Денежные суммы — ``Decimal`` (float для денег запрещён).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core.clock import utc_now
from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.vehicle_profile import BodyType


@dataclass(frozen=True, slots=True)
class Cargo:
    """Груз, нормализованный из внешнего источника (черновой контракт).

    ``required_body_type is None`` — тип кузова не важен;
    ``loading_region`` / ``unloading_region`` — строки как в источнике
    (нормализация регионов появится вместе с реальными источниками).
    """

    id: str
    source_id: str
    title: str = ""
    url: str = ""
    category: CargoCategory = CargoCategory.GENERAL
    weight_kg: int | None = None
    length_cm: int | None = None
    width_cm: int | None = None
    height_cm: int | None = None
    volume_m3: float | None = None
    pallet_count: int | None = None
    required_body_type: BodyType | None = None
    loading_region: str = ""
    unloading_region: str = ""
    payment_amount: Decimal | None = None
    distance_km: float | None = None
    created_at: datetime = field(default_factory=utc_now)  # момент получения из источника
    raw: Mapping[str, object] = field(default_factory=dict)
