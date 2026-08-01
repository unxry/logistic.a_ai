"""Настройка системного логирования LogistAI (ADR-0011).

Три получателя каждой записи:
1. файл ``app.log`` с ротацией (macOS: ~/Library/Logs/LogistAI/);
2. кольцевой буфер последних записей — порт LogBuffer для страницы «Логи»;
3. (опционально) EventBus — событие LogRecordAdded для живой ленты.

Каждую строку лога в SQLite НЕ пишем — журнал событий и логи это разные
вещи (ADR-0011).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.ports import EventPublisher
from app.infrastructure.logging.event_bus_handler import EventBusLogHandler
from app.infrastructure.logging.ring_buffer import DEFAULT_CAPACITY, RingBufferHandler

LOG_FILENAME = "app.log"
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(
    logs_dir: Path,
    *,
    event_bus: EventPublisher | None = None,
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    max_bytes: int = 1_000_000,
    backup_count: int = 5,
    ring_capacity: int = DEFAULT_CAPACITY,
) -> RingBufferHandler:
    """Настроить логирование; вернуть кольцевой буфер (реализацию LogBuffer).

    Идемпотентно для одного logger'а: если буфер уже подключён,
    возвращается существующий (повторная настройка не дублирует handler'ы).
    ``logger`` по умолчанию — корневой (перехватываются и логи библиотек).
    """
    target = logger if logger is not None else logging.getLogger()

    for handler in target.handlers:
        if isinstance(handler, RingBufferHandler):
            return handler

    logs_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        logs_dir / LOG_FILENAME,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    target.addHandler(file_handler)

    ring = RingBufferHandler(capacity=ring_capacity)
    target.addHandler(ring)

    if event_bus is not None:
        target.addHandler(EventBusLogHandler(event_bus))

    target.setLevel(level)
    return ring
