"""Тесты системы логирования: файл, ротация, кольцевой буфер, события."""

from __future__ import annotations

import logging
from pathlib import Path

from app.buses import EventBus
from app.core.events import LogRecordAdded
from app.core.ports import LogBuffer
from app.infrastructure.logging.event_bus_handler import EventBusLogHandler
from app.infrastructure.logging.ring_buffer import RingBufferHandler
from app.infrastructure.logging.setup import setup_logging


def _fresh_logger(name: str) -> logging.Logger:
    """Изолированный logger (не root), чтобы тесты не влияли друг на друга."""
    logger = logging.Logger(name)
    logger.setLevel(logging.DEBUG)
    return logger


def test_file_logging_writes_to_app_log(tmp_path: Path) -> None:
    logger = _fresh_logger("t-file")
    setup_logging(tmp_path, logger=logger)

    logger.info("привет, журнал")
    logging.shutdown()

    content = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "привет, журнал" in content
    assert "INFO" in content


def test_rotation_creates_backup_files(tmp_path: Path) -> None:
    logger = _fresh_logger("t-rot")
    setup_logging(tmp_path, logger=logger, max_bytes=300, backup_count=2)

    for i in range(30):
        logger.info("строка %02d %s", i, "x" * 60)

    assert (tmp_path / "app.log").exists()
    assert (tmp_path / "app.log.1").exists()  # ротация сработала


def test_setup_is_idempotent(tmp_path: Path) -> None:
    logger = _fresh_logger("t-idem")
    ring_first = setup_logging(tmp_path, logger=logger)
    ring_second = setup_logging(tmp_path, logger=logger)

    assert ring_first is ring_second
    assert sum(isinstance(h, RingBufferHandler) for h in logger.handlers) == 1


def test_ring_buffer_keeps_last_records_in_order() -> None:
    ring = RingBufferHandler(capacity=3)
    logger = _fresh_logger("t-ring")
    logger.addHandler(ring)

    for i in range(5):
        logger.info("сообщение %d", i)

    messages = [record.message for record in ring.snapshot()]
    assert messages == ["сообщение 2", "сообщение 3", "сообщение 4"]

    limited = ring.snapshot(limit=2)
    assert [r.message for r in limited] == ["сообщение 3", "сообщение 4"]


def test_ring_buffer_satisfies_log_buffer_port() -> None:
    assert isinstance(RingBufferHandler(), LogBuffer)


def test_log_record_added_event_published() -> None:
    bus = EventBus()
    received: list[LogRecordAdded] = []
    bus.subscribe(LogRecordAdded, received.append)

    logger = _fresh_logger("t-event")
    logger.addHandler(EventBusLogHandler(bus))
    logger.warning("что-то пошло не так")

    assert len(received) == 1
    event = received[0]
    assert event.level == "WARNING"
    assert event.logger_name == "t-event"
    assert "что-то пошло не так" in event.message
    assert event.occurred_at.tzinfo is not None


def test_recursion_guard_prevents_log_event_loop() -> None:
    """Подписчик LogRecordAdded сам пишет в лог — цикла быть не должно."""
    bus = EventBus()
    logger = _fresh_logger("t-recursion")
    logger.addHandler(EventBusLogHandler(bus))

    received: list[LogRecordAdded] = []

    def noisy_subscriber(event: LogRecordAdded) -> None:
        received.append(event)
        logger.info("лог изнутри подписчика")  # повторный вход должен быть пропущен

    bus.subscribe(LogRecordAdded, noisy_subscriber)
    logger.info("исходное сообщение")

    assert len(received) == 1
    assert "исходное сообщение" in received[0].message
