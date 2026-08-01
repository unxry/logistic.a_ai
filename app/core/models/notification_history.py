"""Read-model истории уведомлений для отдельного Timeline-экрана."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from app.core.clock import utc_now


class NotificationOpenState(Enum):
    """Открывал ли пользователь уведомление."""

    UNOPENED = "unopened"
    OPENED = "opened"


@dataclass(frozen=True, slots=True)
class NotificationHistoryEntry:
    """Уведомление с логистическим контекстом, пригодное для аналитики."""

    id: str
    notification_id: str
    occurred_at: datetime
    type: str
    source: str
    route: str = ""
    profit: Decimal | None = None
    ai_score: int | None = None
    open_state: NotificationOpenState = NotificationOpenState.UNOPENED
    cargo_id: str = ""
    trace_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        notification_id: str,
        type: str,
        source: str,
        route: str = "",
        profit: Decimal | None = None,
        ai_score: int | None = None,
        cargo_id: str = "",
        trace_id: str = "",
    ) -> NotificationHistoryEntry:
        """Создать запись истории уведомлений."""
        return cls(
            id=uuid4().hex,
            notification_id=notification_id,
            occurred_at=utc_now(),
            type=type,
            source=source,
            route=route,
            profit=profit,
            ai_score=ai_score,
            cargo_id=cargo_id,
            trace_id=trace_id,
        )
