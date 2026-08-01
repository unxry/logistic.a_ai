"""Порт чтения последних записей лога (для страницы «Логи» в UI).

UI не импортирует инфраструктуру — только этот порт; реализация —
кольцевой буфер поверх logging (``infrastructure/logging``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.models.log_record import LogRecordSnapshot


@runtime_checkable
class LogBuffer(Protocol):
    """Кольцевой буфер последних записей лога."""

    def snapshot(self, limit: int | None = None) -> Sequence[LogRecordSnapshot]:
        """Снимок последних записей (новые — последними)."""
        ...
