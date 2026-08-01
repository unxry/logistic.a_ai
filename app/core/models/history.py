"""История событий — единый журнал работы приложения.

Не «история уведомлений»: журнал фиксирует уведомления, ошибки, события
источников, действия пользователя и системные события. Хранение — порт
``HistoryRepository`` (SQLite). ``trace_id`` связывает запись со всем
жизненным циклом уведомления/груза (корреляция).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.severity import Severity


class HistoryKind(Enum):
    """Тип записи журнала."""

    NOTIFICATION = "notification"
    ERROR = "error"
    SOURCE_EVENT = "source_event"
    USER_ACTION = "user_action"
    SYSTEM_EVENT = "system_event"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Запись журнала.

    ``source`` — кто записал («telegram», «scheduler», «app», id плагина…);
    ``details`` — человекочитаемые подробности (без секретов!);
    ``trace_id`` — сквозная корреляция с уведомлением/процессом.
    """

    id: str
    occurred_at: datetime
    kind: HistoryKind
    severity: Severity
    title: str
    details: str = ""
    source: str = ""
    trace_id: str = ""

    @classmethod
    def create(
        cls,
        kind: HistoryKind,
        severity: Severity,
        title: str,
        details: str = "",
        source: str = "",
        trace_id: str = "",
    ) -> HistoryEntry:
        """Создать запись с новым id и текущим временем UTC."""
        return cls(
            id=uuid4().hex,
            occurred_at=utc_now(),
            kind=kind,
            severity=severity,
            title=title,
            details=details,
            source=source,
            trace_id=trace_id,
        )
