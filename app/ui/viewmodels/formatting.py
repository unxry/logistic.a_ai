"""Форматирование «красивых данных» для UI (чистые функции, без Qt).

Единый стиль отображения: разряды отбиваются пробелом («120 000 ₽»),
отсутствующие данные — короткое тире. Все функции детерминированы
(время — только через переданный ``now``), поэтому пригодны для
снапшот-тестов.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

EMPTY = "—"

_MINUTE_SECONDS = 60
_HOUR_SECONDS = 60 * 60
_DAY_SECONDS = 24 * 60 * 60


def group_digits(value: int) -> str:
    """120000 → «120 000»."""
    return f"{value:,d}".replace(",", " ")


def money(value: Decimal) -> str:
    """Деньги: «120 000 ₽» (копейки в UI не показываются)."""
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def rate_per_km(value: Decimal) -> str:
    """Ставка: «120 ₽/км»."""
    return f"{round(value)} ₽/км"


def weight_kg(value: int | None) -> str:
    """Вес: «5 000 кг»; нет данных — тире."""
    return f"{group_digits(value)} кг" if value is not None else EMPTY


def distance_km(value: float | None) -> str:
    """Расстояние: «710 км»; нет данных — тире."""
    return f"{round(value)} км" if value is not None and value > 0 else EMPTY


def volume_m3(value: float | None) -> str:
    """Объём: «38 м³»; нет данных — тире."""
    return f"{value:g} м³" if value is not None else EMPTY


def dimensions_cm(length: int | None, width: int | None, height: int | None) -> str:
    """Габариты: «500 × 200 × 220 см»; неполные данные — тире."""
    if length is None or width is None or height is None:
        return EMPTY
    return f"{length} × {width} × {height} см"


def relative_time(moment: datetime, now: datetime) -> str:
    """«только что» / «5 мин назад» / «3 ч назад» / «31.07»."""
    seconds = (now - moment).total_seconds()
    if seconds < _MINUTE_SECONDS:
        return "только что"
    if seconds < _HOUR_SECONDS:
        return f"{int(seconds // _MINUTE_SECONDS)} мин назад"
    if seconds < _DAY_SECONDS:
        return f"{int(seconds // _HOUR_SECONDS)} ч назад"
    return moment.strftime("%d.%m")
