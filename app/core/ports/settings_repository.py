"""Порт хранилища настроек."""

from __future__ import annotations

from typing import Protocol

from app.core.models.settings import AppSettings


class SettingsRepository(Protocol):
    """Загрузка/сохранение настроек (реализация: JSON с атомарной записью)."""

    def load(self) -> AppSettings:
        """Прочитать настройки; при отсутствии файла — дефолты."""
        ...

    def save(self, settings: AppSettings) -> None:
        """Атомарно сохранить настройки."""
        ...
