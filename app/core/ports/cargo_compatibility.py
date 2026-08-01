"""Порт проверки совместимости груза и профиля транспорта."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import CompatibilityResult
from app.core.models.logistics.vehicle_profile import VehicleProfile


@runtime_checkable
class CargoCompatibilityChecker(Protocol):
    """«Подходит ли груз этому автомобилю» — чистая функция домена, без I/O.

    Реализация по умолчанию — ``BasicCompatibilityChecker``; альтернативные
    алгоритмы смогут предоставлять плагины.
    """

    def check(self, cargo: Cargo, vehicle: VehicleProfile) -> CompatibilityResult:
        """Проверить совместимость; исключений не бросает."""
        ...
