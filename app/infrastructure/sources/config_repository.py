"""JSON-репозиторий пользовательских конфигураций источников.

Файл ``sources.json`` рядом с настройками: атомарная запись, толерантный
парсинг (битая запись пропускается с логом). Перенос в SQLite — позже,
за тем же портом.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.clock import utc_now
from app.core.errors import StorageError, UnknownSourceError
from app.core.models.sources import SourceConfiguration

logger = logging.getLogger(__name__)


class JsonSourceConfigurationRepository:
    """Реализация порта SourceConfigurationRepository."""

    def __init__(self, file_path: Path) -> None:
        self._path = file_path

    def get_all(self) -> tuple[SourceConfiguration, ...]:
        """Все конфигурации (битые записи пропускаются)."""
        if not self._path.exists():
            return ()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Файл конфигураций источников не читается: %s", exc)
            return ()
        items = data.get("configurations") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return ()
        configurations: list[SourceConfiguration] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            try:
                configurations.append(self._from_dict(item))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Пропущена битая конфигурация источника: %s", exc)
        return tuple(configurations)

    def get(self, source_id: str) -> SourceConfiguration | None:
        """Конфигурация источника; ``None`` — не настроен."""
        for configuration in self.get_all():
            if configuration.source_id == source_id:
                return configuration
        return None

    def save(self, configuration: SourceConfiguration) -> None:
        """Создать или обновить конфигурацию (по source_id), атомарно."""
        others = [c for c in self.get_all() if c.source_id != configuration.source_id]
        self._write((*others, replace(configuration, updated_at=utc_now())))

    def delete(self, source_id: str) -> None:
        """Удалить конфигурацию (отсутствующая — не ошибка)."""
        remaining = tuple(c for c in self.get_all() if c.source_id != source_id)
        self._write(remaining)

    def enable(self, source_id: str) -> None:
        """Включить источник."""
        self._set_enabled(source_id, enabled=True)

    def disable(self, source_id: str) -> None:
        """Выключить источник."""
        self._set_enabled(source_id, enabled=False)

    def _set_enabled(self, source_id: str, *, enabled: bool) -> None:
        configuration = self.get(source_id)
        if configuration is None:
            raise UnknownSourceError(source_id)
        self.save(replace(configuration, enabled=enabled))

    def _write(self, configurations: tuple[SourceConfiguration, ...]) -> None:
        payload = json.dumps(
            {"configurations": [self._to_dict(c) for c in configurations]},
            ensure_ascii=False,
            indent=2,
        )
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(payload + "\n", encoding="utf-8")
            os.replace(tmp_path, self._path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise StorageError(f"Не удалось сохранить конфигурации источников: {exc}") from exc

    @staticmethod
    def _to_dict(configuration: SourceConfiguration) -> dict[str, Any]:
        return {
            "id": configuration.id,
            "source_id": configuration.source_id,
            "enabled": configuration.enabled,
            "name": configuration.name,
            "credentials_reference": configuration.credentials_reference,
            "polling_interval_seconds": configuration.polling_interval_seconds,
            "max_results": configuration.max_results,
            "filters": dict(configuration.filters),
            "created_at": configuration.created_at.isoformat(),
            "updated_at": configuration.updated_at.isoformat(),
        }

    @staticmethod
    def _from_dict(item: Mapping[str, Any]) -> SourceConfiguration:
        filters = item.get("filters")
        return SourceConfiguration(
            id=str(item["id"]),
            source_id=str(item["source_id"]),
            enabled=bool(item["enabled"]),
            name=str(item.get("name", "")),
            credentials_reference=str(item.get("credentials_reference", "")),
            polling_interval_seconds=int(item.get("polling_interval_seconds", 300)),
            max_results=int(item.get("max_results", 100)),
            filters={str(k): str(v) for k, v in filters.items()}
            if isinstance(filters, Mapping)
            else {},
            created_at=datetime.fromisoformat(str(item["created_at"])),
            updated_at=datetime.fromisoformat(str(item["updated_at"])),
        )
