"""NotificationService — оркестратор Notification Center.

Единственная операция для любого модуля платформы:

    await notification_service.send(notification)

Модуль не знает ни о Telegram, ни о macOS, ни о SQLite, ни об очередях.
Сервис только координирует: Router → Dispatcher → журнал → события.
Форматированием занимаются форматтеры, транспортом — каналы, хранением —
HistoryRepository (SQLite сервису неизвестен).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from decimal import Decimal, InvalidOperation

from app.core.errors import StorageError
from app.core.events import (
    NotificationDelivered,
    NotificationFailed,
    NotificationQueued,
    NotificationSending,
)
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.notification import DeliveryReport, Notification
from app.core.models.notification_history import NotificationHistoryEntry
from app.core.models.severity import Severity
from app.core.ports import EventPublisher, HistoryRepository, NotificationHistoryRepository
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.notifications.router import NotificationRouter

logger = logging.getLogger(__name__)


class NotificationService:
    """Центральная точка отправки уведомлений (очередь + оркестрация)."""

    def __init__(
        self,
        *,
        router: NotificationRouter,
        dispatcher: NotificationDispatcher,
        history: HistoryRepository,
        event_bus: EventPublisher,
        notification_history: NotificationHistoryRepository | None = None,
    ) -> None:
        self._router = router
        self._dispatcher = dispatcher
        self._history = history
        self._notification_history = notification_history
        self._events = event_bus
        self._queue: asyncio.Queue[Notification] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    # ── Публичный контракт ────────────────────────────────────────────────────

    async def send(self, notification: Notification) -> None:
        """Поставить уведомление в очередь доставки (не блокирует)."""
        self._ensure_worker()
        await self._queue.put(notification)
        self._events.publish(NotificationQueued(notification=notification))

    async def deliver_now(self, notification: Notification) -> DeliveryReport:
        """Доставить немедленно, минуя очередь (интерактивные сценарии)."""
        return await self._process(notification)

    async def flush(self) -> None:
        """Дождаться доставки всего, что лежит в очереди."""
        await self._queue.join()

    async def aclose(self) -> None:
        """Остановить воркер очереди (graceful shutdown)."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

    # ── Оркестрация ───────────────────────────────────────────────────────────

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.get_running_loop().create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            notification = await self._queue.get()
            try:
                await self._process(notification)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification Center: необработанная ошибка доставки")
            finally:
                self._queue.task_done()

    async def _process(self, notification: Notification) -> DeliveryReport:
        channels = self._router.route(notification)
        self._events.publish(
            NotificationSending(
                notification_id=notification.id,
                trace_id=notification.trace_id,
                channels=channels,
            )
        )

        report = await self._dispatcher.dispatch(notification, channels)

        await self._record_history(notification, report)
        if report.delivered_any:
            logger.info(
                "Уведомление доставлено: %s за %d мс",
                ", ".join(report.successful_channels),
                report.duration_ms,
            )
            self._events.publish(NotificationDelivered(report=report))
        else:
            logger.warning(
                "Уведомление не доставлено ни в один канал (%s)",
                ", ".join(report.failed_channels) or "каналов нет",
            )
            self._events.publish(NotificationFailed(report=report))
        return report

    async def _record_history(self, notification: Notification, report: DeliveryReport) -> None:
        """Записать итог в журнал; сбой журнала не должен ломать доставку."""
        if report.delivered_any:
            severity = notification.severity
            details = f"Доставлено: {', '.join(report.successful_channels)}"
            if report.failed_channels:
                failures = "; ".join(f"{r.channel_id}: {r.error}" for r in report.failed())
                details += f". Ошибки: {failures}"
        else:
            severity = Severity.WARNING
            details = "Не доставлено. " + "; ".join(
                f"{r.channel_id}: {r.error}" for r in report.failed()
            )

        kind = (
            HistoryKind.USER_ACTION
            if notification.context.user_action
            else HistoryKind.NOTIFICATION
        )
        entry = HistoryEntry.create(
            kind=kind,
            severity=severity,
            title=notification.title,
            details=details,
            source=notification.context.source,
            trace_id=notification.trace_id,
        )
        try:
            await self._history.add(entry)
        except StorageError:
            logger.exception("Не удалось записать уведомление в журнал")

        notification_history = self._notification_history
        if notification_history is not None:
            await self._record_notification_history(notification, notification_history)

    async def _record_notification_history(
        self,
        notification: Notification,
        notification_history: NotificationHistoryRepository,
    ) -> None:
        payload = notification.payload
        profit: Decimal | None = None
        raw_profit = payload.get("profit")
        if raw_profit:
            try:
                profit = Decimal(raw_profit)
            except InvalidOperation:
                profit = None
        raw_score = payload.get("ai_score")
        try:
            score = int(raw_score) if raw_score else None
        except ValueError:
            score = None
        entry = NotificationHistoryEntry.create(
            notification_id=notification.id,
            type=notification.category.value,
            source=notification.context.source,
            route=payload.get("route", ""),
            profit=profit,
            ai_score=score,
            cargo_id=payload.get("cargo_id", ""),
            trace_id=notification.trace_id,
        )
        try:
            await notification_history.add(entry)
        except StorageError:
            logger.exception("Не удалось записать историю уведомления")
