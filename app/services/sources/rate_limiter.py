"""Token-bucket ограничитель частоты обращений к источнику.

Ёмкость — burst_limit, пополнение — requests_per_minute/60 токенов в секунду.
requests_per_minute <= 0 означает «без ограничений».
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from app.core.models.sources import SourceRateLimitPolicy

logger = logging.getLogger(__name__)


class SourceRateLimiter:
    """Лимитер одного источника."""

    def __init__(self, policy: SourceRateLimitPolicy) -> None:
        self._policy = policy
        self._capacity = float(max(1, policy.burst_limit))
        self._refill_per_second = policy.requests_per_minute / 60.0
        self._tokens = self._capacity
        self._updated_at = monotonic()

    async def acquire(self, source_id: str) -> float:
        """Получить право на запрос; вернуть, сколько пришлось ждать (сек)."""
        if self._policy.requests_per_minute <= 0:
            return 0.0
        waited = 0.0
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return waited
            shortfall = (1.0 - self._tokens) / self._refill_per_second
            logger.warning(
                "Источник «%s»: превышен лимит запросов, ожидание %.2f с",
                source_id,
                shortfall,
            )
            await asyncio.sleep(shortfall)
            waited += shortfall

    def _refill(self) -> None:
        now = monotonic()
        elapsed = now - self._updated_at
        self._updated_at = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_second)
