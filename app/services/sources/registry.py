"""Реестр источников грузов.

Регистрация без if-ов: ``registry.register(source)`` (bootstrap или плагин
через PluginExtensions.add_source).
"""

from __future__ import annotations

from app.core.errors import DuplicateSourceError, UnknownSourceError
from app.core.events import SourceRegistered
from app.core.models.sources import SourceDescriptor
from app.core.ports import CargoSource, EventPublisher


class SourceRegistry:
    """Именованный реестр источников."""

    def __init__(self, event_bus: EventPublisher | None = None) -> None:
        self._sources: dict[str, CargoSource] = {}
        self._events = event_bus

    def register(self, source: CargoSource) -> None:
        """Зарегистрировать источник; повторный id — ошибка (признак бага)."""
        source_id = source.spec.id
        if source_id in self._sources:
            raise DuplicateSourceError(source_id)
        self._sources[source_id] = source
        if self._events is not None:
            self._events.publish(SourceRegistered(source_id=source_id, name=source.spec.name))

    def remove(self, source_id: str) -> None:
        """Убрать источник из реестра; неизвестный id — ошибка."""
        if source_id not in self._sources:
            raise UnknownSourceError(source_id)
        del self._sources[source_id]

    def get(self, source_id: str) -> CargoSource:
        """Источник по id; неизвестный id — ошибка."""
        source = self._sources.get(source_id)
        if source is None:
            raise UnknownSourceError(source_id)
        return source

    def ids(self) -> tuple[str, ...]:
        """Идентификаторы всех источников."""
        return tuple(self._sources)

    def all(self) -> tuple[CargoSource, ...]:
        """Все зарегистрированные источники."""
        return tuple(self._sources.values())

    def list_available_sources(self) -> tuple[SourceDescriptor, ...]:
        """Каталог источников для UI: что можно подключить и настроить."""
        return tuple(
            SourceDescriptor(
                id=source.spec.id,
                name=source.spec.name,
                version=source.spec.version,
                source_type=source.spec.source_type,
                capabilities=source.spec.capabilities,
                requires_credentials=source.spec.requires_credentials,
                supported_regions=source.spec.supported_regions,
            )
            for source in self._sources.values()
        )
