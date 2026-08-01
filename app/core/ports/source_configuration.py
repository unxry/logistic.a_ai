"""Порт хранилища пользовательских конфигураций источников."""

from __future__ import annotations

from typing import Protocol

from app.core.models.sources import SourceConfiguration


class SourceConfigurationRepository(Protocol):
    """Хранение настроек источников (JSON сейчас, SQLite позже)."""

    def get_all(self) -> tuple[SourceConfiguration, ...]:
        """Все конфигурации."""
        ...

    def get(self, source_id: str) -> SourceConfiguration | None:
        """Конфигурация источника; ``None`` — не настроен."""
        ...

    def save(self, configuration: SourceConfiguration) -> None:
        """Создать или обновить конфигурацию (по source_id)."""
        ...

    def delete(self, source_id: str) -> None:
        """Удалить конфигурацию (отсутствующая — не ошибка)."""
        ...

    def enable(self, source_id: str) -> None:
        """Включить источник; нет конфигурации — ошибка UnknownSourceError."""
        ...

    def disable(self, source_id: str) -> None:
        """Выключить источник; нет конфигурации — ошибка UnknownSourceError."""
        ...
