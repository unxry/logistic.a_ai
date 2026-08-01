"""Публикация записей лога в EventBus (событие LogRecordAdded).

Нужна живой ленте логов в UI. Зависит от порта EventPublisher, а не от
``app.buses`` — контракт «infrastructure → только core» соблюдён.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.events import LogRecordAdded
from app.core.ports import EventPublisher


class EventBusLogHandler(logging.Handler):
    """logging.Handler → LogRecordAdded.

    Защита от рекурсии: публикация события может снова породить лог
    (например, упавший подписчик EventBus пишет в лог, шина логирует это,
    обработчик публикует событие, подписчик снова падает…). Повторный вход
    пропускается; приложение однопоточное (qasync), флага достаточно.
    """

    def __init__(self, publisher: EventPublisher, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self._publisher = publisher
        self._publishing = False

    def emit(self, record: logging.LogRecord) -> None:
        """Опубликовать запись как событие (с защитой от повторного входа)."""
        if self._publishing:
            return
        self._publishing = True
        try:
            self._publisher.publish(
                LogRecordAdded(
                    occurred_at=datetime.fromtimestamp(record.created, tz=UTC),
                    level=record.levelname,
                    logger_name=record.name,
                    message=record.getMessage(),
                )
            )
        except Exception:
            self.handleError(record)
        finally:
            self._publishing = False
