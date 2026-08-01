"""NotificationCooldownPolicy — защита от спама повторными уведомлениями.

Одна и та же проблема (ключ) в пределах окна уведомляет ОДИН раз:
«ATI упал» в 10:00, 10:01, 10:02 → одно сообщение. Восстановление сбрасывает
ключ (``reset``) — следующая авария уведомит немедленно. Политика общая для
любых уведомлений (не только источников), ключи выбирает вызывающий.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.core.clock import utc_now

DEFAULT_COOLDOWN_SECONDS = 180.0  # 3 минуты (пример из ТЗ)


class NotificationCooldownPolicy:
    """«Не чаще одного уведомления на ключ в окно»."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._window_seconds = window_seconds
        self._clock = clock
        self._last_sent: dict[str, datetime] = {}

    def should_send(self, key: str) -> bool:
        """Можно ли отправить сейчас (и, если да, зафиксировать отправку)."""
        now = self._clock()
        last = self._last_sent.get(key)
        if last is not None and (now - last).total_seconds() < self._window_seconds:
            return False
        self._last_sent[key] = now
        return True

    def reset(self, key: str) -> None:
        """Сбросить ключ (проблема ушла — следующая уведомит сразу)."""
        self._last_sent.pop(key, None)

    def suppressed(self, key: str) -> bool:
        """Находится ли ключ в окне подавления (без фиксации отправки)."""
        last = self._last_sent.get(key)
        if last is None:
            return False
        return (self._clock() - last).total_seconds() < self._window_seconds
