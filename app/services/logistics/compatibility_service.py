"""Сервис совместимости грузов и транспорта (задел этапа 1.5).

Сейчас — тонкая обёртка над портом ``CargoCompatibilityChecker`` (DI).
После появления реальных источников (v0.2) сюда добавятся: выбор активного
профиля из настроек, батч-проверка входящих грузов, публикация событий
и запись в журнал. Контракт метода ``check`` при этом не изменится.
"""

from __future__ import annotations

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import CompatibilityResult
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.ports import CargoCompatibilityChecker


class CargoCompatibilityService:
    """Application-сервис проверки совместимости."""

    def __init__(self, checker: CargoCompatibilityChecker) -> None:
        self._checker = checker

    def check(self, cargo: Cargo, vehicle: VehicleProfile) -> CompatibilityResult:
        """Проверить совместимость груза с профилем транспорта."""
        return self._checker.check(cargo, vehicle)
