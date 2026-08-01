"""Миграции схемы настроек.

Файл настроек несёт ``schema_version``. При загрузке ``JsonSettingsRepository``
прогоняет данные через цепочку миграций до текущей версии
(``app.core.models.settings.SCHEMA_VERSION``).

Правила миграций:
- миграция — чистая функция ``dict → dict`` без I/O;
- обязана поднять ``schema_version`` ровно на 1 (проверяется движком);
- новая миграция: модуль ``vNNNN_описание.py`` с функцией ``migrate`` +
  регистрация в ``MIGRATIONS`` здесь.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.core.errors import SettingsMigrationError
from app.infrastructure.settings.migrations.v0001_route_settings import (
    migrate as _v0001_route_settings,
)

Migration = Callable[[dict[str, Any]], dict[str, Any]]

MIGRATIONS: dict[int, Migration] = {
    1: _v0001_route_settings,  # 1 → 2: секции routing и matching (Stage 8.5)
}


def apply_migrations(
    data: dict[str, Any],
    migrations: Mapping[int, Migration],
    target_version: int,
) -> dict[str, Any]:
    """Прогнать данные через цепочку миграций до ``target_version``.

    Бросает ``SettingsMigrationError``, если версия некорректна, новее
    приложения, отсутствует шаг цепочки или миграция не подняла версию.
    """
    raw_version = data.get("schema_version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise SettingsMigrationError(f"Некорректная версия схемы настроек: {raw_version!r}")
    version = raw_version
    if version > target_version:
        raise SettingsMigrationError(
            f"Настройки созданы более новой версией приложения (схема {version} > {target_version})"
        )
    while version < target_version:
        step = migrations.get(version)
        if step is None:
            raise SettingsMigrationError(f"Нет миграции настроек {version} → {version + 1}")
        data = step(data)
        if data.get("schema_version") != version + 1:
            raise SettingsMigrationError(
                f"Миграция {version} → {version + 1} не подняла версию схемы"
            )
        version += 1
    return data
