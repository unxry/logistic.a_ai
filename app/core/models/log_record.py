"""Снимок записи лога для отображения в UI (страница «Журнал/Логи»).

UI читает логи через порт ``LogBuffer`` — не через инфраструктуру напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LogRecordSnapshot:
    """Одна строка лога, подготовленная для UI."""

    occurred_at: datetime
    level: str
    logger_name: str
    message: str
