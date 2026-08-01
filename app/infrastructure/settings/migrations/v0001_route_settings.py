"""Миграция настроек 1 → 2: секции routing и matching (Stage 8.5).

Значения не переписываются: секции создаются пустыми, дефолты тарифов
и весов подставит толерантный парсер (единственный источник дефолтов —
модели ядра).
"""

from __future__ import annotations

from typing import Any


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Добавить секции экономики маршрутов и весов подбора."""
    migrated = dict(data)
    migrated.setdefault("routing", {})
    migrated.setdefault("matching", {})
    migrated["schema_version"] = 2
    return migrated
