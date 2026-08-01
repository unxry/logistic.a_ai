"""События настроек."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.settings import AppSettings


@dataclass(frozen=True, slots=True)
class SettingsChanged(Event):
    """Настройки сохранены; несёт новый снимок настроек."""

    settings: AppSettings
