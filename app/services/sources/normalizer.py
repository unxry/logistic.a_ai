"""CargoNormalizer — преобразование RawCargo → доменный Cargo.

Единственная ответственность: единицы измерения (кг/тонны, см/метры, м³),
категории, типы кузова и нормализация регионов. Непарсибельные значения
становятся ``None`` — проверка совместимости честно предупредит о неполных
данных, а не отбросит груз. Поиск — не забота нормализатора.

Эвристики единиц (зафиксированы тестами):
- вес: «т»/«тонн» → ×1000; «кг» → как есть; без метки: < 100 → тонны, иначе кг;
- длина/ширина/высота: «см» → как есть; «м» → ×100; без метки: < 20 → метры;
- объём: число в м³.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.vehicle_profile import BodyType
from app.core.models.sources import (
    ATTR_BODY_TYPE,
    ATTR_CATEGORY,
    ATTR_DISTANCE_KM,
    ATTR_HEIGHT,
    ATTR_LENGTH,
    ATTR_LOADING_REGION,
    ATTR_PALLETS,
    ATTR_PRICE,
    ATTR_UNLOADING_REGION,
    ATTR_VOLUME,
    ATTR_WEIGHT,
    ATTR_WIDTH,
    RawCargo,
)

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

_WEIGHT_TONS_BELOW = 100.0  # число без метки меньше порога — тонны
_LENGTH_METERS_BELOW = 20.0  # размер без метки меньше порога — метры

_CATEGORY_KEYWORDS: tuple[tuple[str, CargoCategory], ...] = (
    ("паллет", CargoCategory.PALLET),
    ("продукт", CargoCategory.FOOD),
    ("еда", CargoCategory.FOOD),
    ("питан", CargoCategory.FOOD),
    ("стройматериал", CargoCategory.BUILDING_MATERIALS),
    ("строит", CargoCategory.BUILDING_MATERIALS),
    ("оборудован", CargoCategory.EQUIPMENT),
    ("мебель", CargoCategory.FURNITURE),
    ("бытов", CargoCategory.HOUSEHOLD),
    ("реф", CargoCategory.TEMPERATURE_CONTROLLED),
    ("температур", CargoCategory.TEMPERATURE_CONTROLLED),
)

_BODY_TYPE_KEYWORDS: tuple[tuple[str, BodyType], ...] = (
    ("тент", BodyType.TENT),
    ("реф", BodyType.REFRIGERATOR),
    ("изотерм", BodyType.ISOTHERMAL),
    ("фургон", BodyType.BOX),
    ("борт", BodyType.FLATBED),
    ("контейнер", BodyType.CONTAINER),
)


class CargoNormalizer:
    """Нормализация «сырых» грузов источников в доменную модель."""

    def normalize(self, raw: RawCargo, source_id: str) -> Cargo:
        """RawCargo → Cargo (непарсибельные поля → None)."""
        attrs = raw.attributes
        return Cargo(
            id=raw.external_id or uuid4().hex,
            source_id=source_id,
            title=raw.title.strip(),
            url=raw.url,
            category=self._category(attrs.get(ATTR_CATEGORY, "")),
            weight_kg=self._weight_kg(attrs.get(ATTR_WEIGHT)),
            length_cm=self._size_cm(attrs.get(ATTR_LENGTH)),
            width_cm=self._size_cm(attrs.get(ATTR_WIDTH)),
            height_cm=self._size_cm(attrs.get(ATTR_HEIGHT)),
            volume_m3=self._number(attrs.get(ATTR_VOLUME)),
            pallet_count=self._int(attrs.get(ATTR_PALLETS)),
            required_body_type=self._body_type(attrs.get(ATTR_BODY_TYPE, "")),
            loading_region=self._region(attrs.get(ATTR_LOADING_REGION, "")),
            unloading_region=self._region(attrs.get(ATTR_UNLOADING_REGION, "")),
            payment_amount=self._price(attrs.get(ATTR_PRICE)),
            distance_km=self._number(attrs.get(ATTR_DISTANCE_KM)),
            raw=dict(raw.raw),
        )

    # ── Числа и единицы ───────────────────────────────────────────────────────

    @staticmethod
    def _number(text: str | None) -> float | None:
        if not text:
            return None
        match = _NUMBER.search(text)
        if match is None:
            return None
        return float(match.group().replace(",", "."))

    def _weight_kg(self, text: str | None) -> int | None:
        value = self._number(text)
        if value is None or text is None:
            return None
        lowered = text.lower()
        if "кг" in lowered:
            return round(value)
        if "т" in lowered:  # «т», «тонн», «тонны»
            return round(value * 1000)
        if value < _WEIGHT_TONS_BELOW:
            return round(value * 1000)
        return round(value)

    def _size_cm(self, text: str | None) -> int | None:
        value = self._number(text)
        if value is None or text is None:
            return None
        lowered = text.lower()
        if "см" in lowered:
            return round(value)
        if "м" in lowered:  # «м», «метров» (не «см» — проверено выше)
            return round(value * 100)
        if value < _LENGTH_METERS_BELOW:
            return round(value * 100)
        return round(value)

    def _int(self, text: str | None) -> int | None:
        value = self._number(text)
        return round(value) if value is not None else None

    def _price(self, text: str | None) -> Decimal | None:
        if not text:
            return None
        cleaned = text.replace(" ", "").replace(" ", "")
        match = _NUMBER.search(cleaned)
        if match is None:
            return None
        try:
            return Decimal(match.group().replace(",", "."))
        except InvalidOperation:  # pragma: no cover — regex гарантирует число
            return None

    # ── Категории, кузов, регионы ─────────────────────────────────────────────

    @staticmethod
    def _category(text: str) -> CargoCategory:
        lowered = text.strip().lower()
        if not lowered:
            return CargoCategory.GENERAL
        for keyword, category in _CATEGORY_KEYWORDS:
            if keyword in lowered:
                return category
        return CargoCategory.OTHER

    @staticmethod
    def _body_type(text: str) -> BodyType | None:
        lowered = text.strip().lower()
        if not lowered:
            return None
        for keyword, body_type in _BODY_TYPE_KEYWORDS:
            if keyword in lowered:
                return body_type
        return BodyType.OTHER

    @staticmethod
    def _region(text: str) -> str:
        collapsed = " ".join(text.split())
        if not collapsed:
            return ""
        if collapsed.islower():
            return collapsed.title()
        return collapsed
