"""EventBus — типизированная шина событий (in-process).

Семантика (зафиксирована тестами):
- подписка на КОНКРЕТНЫЙ тип события; иерархия не разворачивается (осознанно:
  диспетчеризация предсказуема, «магических» доставок нет);
- порядок доставки = порядок подписки (детерминизм);
- ошибка подписчика логируется и НЕ прерывает доставку остальным;
- повторная подписка того же обработчика — ошибка (признак бага);
- потокобезопасность не требуется: всё живёт в одной петле qasync (ADR-0003);
  публикация из других потоков появится вместе с worker'ами — отдельным
  методом, а не усложнением этого.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.core.errors import BusError
from app.core.events import Event

logger = logging.getLogger(__name__)


class EventBus:
    """Шина событий: слабая связность сервисов и UI (ADR-0004)."""

    def __init__(self) -> None:
        self._handlers: defaultdict[type[Event], list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe[E: Event](self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Подписать обработчик на тип события."""
        handlers = self._handlers[event_type]
        if handler in handlers:
            raise BusError(f"Обработчик уже подписан на {event_type.__name__}")
        handlers.append(handler)

    def unsubscribe[E: Event](self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Отписать обработчик; отписка неподписанного — ошибка."""
        try:
            self._handlers[event_type].remove(handler)
        except ValueError as exc:
            raise BusError(f"Обработчик не был подписан на {event_type.__name__}") from exc

    def publish(self, event: Event) -> None:
        """Доставить событие всем подписчикам его типа.

        Список копируется: подписка/отписка внутри обработчика безопасна.
        """
        for handler in tuple(self._handlers.get(type(event), ())):
            try:
                handler(event)
            except Exception:
                logger.exception("Подписчик %r упал на событии %s", handler, type(event).__name__)
