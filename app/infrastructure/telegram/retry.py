"""Политика повторов для Telegram Bot API.

Правила (ADR-0012):
- 429 — повтор через retry_after из ответа (если Telegram его прислал);
- 5xx и сетевые ошибки — до max_attempts с экспоненциальной задержкой и джиттером;
- 400 / 401 / 403 / 404 — не повторяются никогда (повтор не исправит запрос).
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Параметры повторов."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.25  # доля случайной добавки к задержке

    def delay_for(self, attempt: int) -> float:
        """Задержка перед следующей попыткой (attempt считается с 1)."""
        base = min(self.max_delay, self.base_delay * (2.0 ** (attempt - 1)))
        # random здесь не криптографический — это джиттер против «толпы» ретраев.
        return base + random.uniform(0, self.jitter * base)
