"""События настроек."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.settings import AppSettings


@dataclass(frozen=True, slots=True)
class SettingsChanged(Event):
    """Настройки сохранены; несёт новый снимок настроек."""

    settings: AppSettings


@dataclass(frozen=True, slots=True)
class ActiveVehicleChanged(Event):
    """Активная машина изменилась; Matching использует новый профиль."""

    vehicle: VehicleProfile | None
