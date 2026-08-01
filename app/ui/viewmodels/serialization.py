"""Детерминированная сериализация ViewModel в JSON-совместимую форму.

Основа снапшот-тестов и удобная отладочная форма контрактов для UI-агента:
dataclass → dict, Enum → value, Decimal → str, datetime → ISO 8601.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def snapshot_dict(value: object) -> Any:
    """Перевести ViewModel (или любую композицию dataclass'ов) в JSON-форму."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: snapshot_dict(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): snapshot_dict(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [snapshot_dict(item) for item in value]
    return value
