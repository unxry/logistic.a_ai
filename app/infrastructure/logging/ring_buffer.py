"""Кольцевой буфер записей лога (реализация порта LogBuffer).

Хранит последние N записей в памяти для страницы «Логи» в UI —
без записи каждой строки в SQLite (осознанно, ADR-0011).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.models.log_record import LogRecordSnapshot

DEFAULT_CAPACITY = 2000


class RingBufferHandler(logging.Handler):
    """logging.Handler, копящий последние записи в deque(maxlen)."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._records: deque[LogRecordSnapshot] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        """Добавить запись в буфер (старые вытесняются автоматически)."""
        try:
            self._records.append(
                LogRecordSnapshot(
                    occurred_at=datetime.fromtimestamp(record.created, tz=UTC),
                    level=record.levelname,
                    logger_name=record.name,
                    message=record.getMessage(),
                )
            )
        except Exception:
            self.handleError(record)

    def snapshot(self, limit: int | None = None) -> Sequence[LogRecordSnapshot]:
        """Снимок последних записей (новые — последними)."""
        self.acquire()
        try:
            records = tuple(self._records)
        finally:
            self.release()
        if limit is None or limit >= len(records):
            return records
        return records[-limit:]
