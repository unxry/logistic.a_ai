"""Категории грузов.

Начальный набор. Расширение — через источники или конфигурацию: адаптеры
источников (v0.2) маппят категории конкретной биржи в наши; незнакомое —
в ``OTHER`` (ядро при этом не меняется).
"""

from __future__ import annotations

from enum import Enum


class CargoCategory(Enum):
    """Категория груза."""

    PALLET = "pallet"
    FOOD = "food"
    BUILDING_MATERIALS = "building_materials"
    EQUIPMENT = "equipment"
    FURNITURE = "furniture"
    HOUSEHOLD = "household"
    TEMPERATURE_CONTROLLED = "temperature_controlled"
    GENERAL = "general"
    OTHER = "other"
