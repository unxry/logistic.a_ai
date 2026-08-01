"""Ограничитель частоты отправки сообщений.

Telegram ограничивает ~1 сообщение в секунду на чат. Если приложение случайно
породит сотню уведомлений, они не полетят залпом: воркер очереди ждёт лимитер
перед каждой отправкой.
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

logger = logging.getLogger(__name__)


class RateLimiter:
    """Минимальный интервал между операциями (asyncio, один поток)."""

    def __init__(self, min_interval: float = 1.0) -> None:
        self._min_interval = min_interval
        self._last_at: float | None = None

    async def wait(self) -> None:
        """Дождаться права на следующую операцию."""
        if self._min_interval <= 0:
            return
        if self._last_at is not None:
            elapsed = monotonic() - self._last_at
            remaining = self._min_interval - elapsed
            if remaining > 0:
                logger.debug("Rate limit: ждём %.2f с перед отправкой", remaining)
                await asyncio.sleep(remaining)
        self._last_at = monotonic()
