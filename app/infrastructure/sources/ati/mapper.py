"""AtiCargoMapper — форматы ATI → RawCargo (нормализация НЕ здесь).

Поддерживаются оба формата ответов:
- «плоский» (Weight/CargoId/LoadingCityName…) — исторические выгрузки;
- вложенный боевой (cargo/loading/unloading/payment…) — loads/search.

Правила: значения кладутся в attributes СТРОКАМИ с пометкой единиц
(конверсию делает CargoNormalizer); комбинированные габариты
«6.2x2.45x2.5» разбиваются на длину/ширину/высоту; неизвестные поля
НЕ теряются — полный payload сохраняется в ``RawCargo.raw`` (raw_metadata).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

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

#: Не-контрактные атрибуты (сохраняются для будущих модулей, поиск их не ждёт).
ATTR_LOADING_DATE = "loading_date"
ATTR_DELIVERY_DEADLINE = "delivery_deadline"

_DIMENSIONS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)"
)


class AtiCargoMapper:
    """Перекладывает поля ответа ATI в атрибуты RawCargo (строки как есть)."""

    def map(self, payload: Mapping[str, Any]) -> RawCargo:
        """Одна карточка груза ATI → RawCargo."""
        attributes: dict[str, str] = {}

        self._put(attributes, ATTR_WEIGHT, self._weight(payload))
        self._map_dimensions(attributes, payload)
        self._put(attributes, ATTR_VOLUME, self._volume(payload))
        self._put(attributes, ATTR_PALLETS, self._pick(payload, "Pallets", "cargo.pallets"))
        self._put(attributes, ATTR_PRICE, self._price(payload))
        self._put(
            attributes,
            ATTR_DISTANCE_KM,
            self._pick(payload, "Distance", "distance", "route.distance"),
        )
        self._put(
            attributes,
            ATTR_CATEGORY,
            self._pick(payload, "CargoTypeName", "cargo.name", "cargo_type"),
        )
        self._put(
            attributes,
            ATTR_BODY_TYPE,
            self._pick(payload, "CarTypeName", "car_type", "transport.body_type"),
        )
        self._put(
            attributes,
            ATTR_LOADING_REGION,
            self._pick(payload, "LoadingCityName", "loading.city_name", "loading.city", "from"),
        )
        self._put(
            attributes,
            ATTR_UNLOADING_REGION,
            self._pick(payload, "UnloadingCityName", "unloading.city_name", "unloading.city", "to"),
        )
        self._put(attributes, ATTR_LOADING_DATE, self._pick(payload, "LoadingDate", "loading.date"))
        self._put(
            attributes,
            ATTR_DELIVERY_DEADLINE,
            self._pick(payload, "DeliveryDeadline", "unloading.date_to", "unloading.date"),
        )

        external_id = self._pick(payload, "CargoId", "id", "cargo_application_id")
        title = self._pick(payload, "CargoTypeName", "cargo.name") or "Груз ATI"
        return RawCargo(
            external_id=str(external_id) if external_id is not None else "",
            title=str(title),
            url=str(self._pick(payload, "Url", "url") or ""),
            attributes=attributes,
            raw=dict(payload),  # raw_metadata: неизвестные поля не теряются
        )

    # ── Извлечение значений ───────────────────────────────────────────────────

    @staticmethod
    def _pick(payload: Mapping[str, Any], *paths: str) -> Any:
        """Первое непустое значение по списку путей («a.b» — вложенность)."""
        for path in paths:
            value: Any = payload
            for part in path.split("."):
                if isinstance(value, Mapping):
                    value = value.get(part)
                else:
                    value = None
                    break
            if value is not None and value != "":
                return value
        return None

    def _weight(self, payload: Mapping[str, Any]) -> str | None:
        """Вес: число (тонны ATI) или объект {quantity, type} или строка «5 т»."""
        value = self._pick(payload, "Weight", "cargo.weight", "weight")
        if value is None:
            return None
        if isinstance(value, Mapping):
            quantity = value.get("quantity")
            unit = str(value.get("type", value.get("unit", "tons")))
            if quantity is None:
                return None
            suffix = " кг" if "kg" in unit or "кг" in unit else " т"
            return f"{quantity}{suffix}"
        if isinstance(value, int | float):
            return f"{value} т"  # единица ATI по умолчанию — тонны
        return str(value)  # строка источника («5 т», «5000 кг») — как есть

    def _volume(self, payload: Mapping[str, Any]) -> str | None:
        value = self._pick(payload, "Volume", "cargo.volume", "volume")
        if value is None:
            return None
        if isinstance(value, int | float):
            return f"{value} м3"
        return str(value)

    def _price(self, payload: Mapping[str, Any]) -> str | None:
        value = self._pick(
            payload, "Price", "payment.rate_sum", "payment.sum", "payment.rate_text", "price"
        )
        return None if value is None else str(value)

    def _map_dimensions(self, attributes: dict[str, str], payload: Mapping[str, Any]) -> None:
        """Габариты: отдельные поля или комбинированная строка.

        Отдельные числовые поля ATI — метры (единица API), суффикс « м».
        Комбинированные строки бывают и «6.2x2.45x2.5» (метры), и
        «620x245x250» (сантиметры) — суффикс НЕ навязывается, эвристика
        CargoNormalizer различает по величине (< 20 — метры).
        """
        length = self._pick(payload, "Length", "cargo.length")
        width = self._pick(payload, "Width", "cargo.width")
        height = self._pick(payload, "Height", "cargo.height")
        suffix = " м"
        if length is None and width is None and height is None:
            combined = self._pick(payload, "Dimensions", "cargo.sizes", "sizes")
            if combined is not None:
                match = _DIMENSIONS.search(str(combined))
                if match is not None:
                    length, width, height = match.groups()
                    suffix = ""  # единицу решает нормализатор
        self._put(attributes, ATTR_LENGTH, length, suffix=suffix)
        self._put(attributes, ATTR_WIDTH, width, suffix=suffix)
        self._put(attributes, ATTR_HEIGHT, height, suffix=suffix)

    @staticmethod
    def _put(attributes: dict[str, str], key: str, value: Any, suffix: str = "") -> None:
        if value is None or value == "":
            return
        text = str(value)
        if suffix and not any(ch.isalpha() for ch in text):
            text = f"{text}{suffix}"
        attributes[key] = text
