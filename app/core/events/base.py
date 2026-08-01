"""База всех доменных событий."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.clock import utc_now


@dataclass(frozen=True, slots=True)
class Event:
    """Событие — свершившийся факт (именуется в прошедшем времени).

    Публикуется в EventBus; подписчиков может быть много. Событие не может
    «провалиться» и не возвращает результата — для намерений есть команды.
    """

    occurred_at: datetime = field(default_factory=utc_now, kw_only=True)
