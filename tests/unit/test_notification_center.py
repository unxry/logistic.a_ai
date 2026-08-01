"""Тесты Notification Center: Router, Registries, Dispatcher, Service, очередь."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime

import pytest

from app.buses import CommandBus, EventBus
from app.core.commands import SendNotification
from app.core.errors import NotificationError
from app.core.events import (
    NotificationDelivered,
    NotificationFailed,
    NotificationQueued,
    NotificationSending,
)
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.notification import DeliveryResult, Notification, NotificationContext
from app.core.models.severity import Severity
from app.services.notifications import (
    ChannelRegistry,
    FormatterRegistry,
    NotificationDispatcher,
    NotificationRouter,
    NotificationService,
    PlainTextFormatter,
    SendNotificationHandler,
)

ENABLED = ("telegram", "macos_native")


class FakeChannel:
    """Канал-фейк: копит отправленное, может отказывать."""

    def __init__(self, channel_id: str, *, fail: bool = False) -> None:
        self._id = channel_id
        self.fail = fail
        self.sent: list[tuple[str, str]] = []  # (notification.title, text)

    @property
    def channel_id(self) -> str:
        return self._id

    async def send(self, notification: Notification, text: str) -> DeliveryResult:
        if self.fail:
            return DeliveryResult(channel_id=self._id, ok=False, error="канал недоступен")
        self.sent.append((notification.title, text))
        return DeliveryResult(channel_id=self._id, ok=True, duration_ms=1)


class InMemoryHistory:
    """Фейк HistoryRepository для тестов сервиса."""

    def __init__(self) -> None:
        self.entries: list[HistoryEntry] = []

    async def add(self, entry: HistoryEntry) -> None:
        self.entries.append(entry)

    async def query(
        self,
        *,
        kind: HistoryKind | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[HistoryEntry]:
        return tuple(self.entries[-limit:])

    async def count(self, *, kind: HistoryKind | None = None, since: datetime | None = None) -> int:
        return len(self.entries)

    async def last(self, *, kind: HistoryKind | None = None) -> HistoryEntry | None:
        return self.entries[-1] if self.entries else None

    async def prune(self, *, before: datetime) -> int:
        return 0


class Center:
    """Собранный Notification Center на фейках."""

    def __init__(self, *, telegram_fails: bool = False, macos_fails: bool = False) -> None:
        self.telegram = FakeChannel("telegram", fail=telegram_fails)
        self.macos = FakeChannel("macos_native", fail=macos_fails)
        self.channels = ChannelRegistry()
        self.channels.register(self.telegram)
        self.channels.register(self.macos)
        self.formatters = FormatterRegistry(default=PlainTextFormatter())
        self.history = InMemoryHistory()
        self.bus = EventBus()

        self.queued: list[NotificationQueued] = []
        self.sending: list[NotificationSending] = []
        self.delivered: list[NotificationDelivered] = []
        self.failed: list[NotificationFailed] = []
        self.bus.subscribe(NotificationQueued, self.queued.append)
        self.bus.subscribe(NotificationSending, self.sending.append)
        self.bus.subscribe(NotificationDelivered, self.delivered.append)
        self.bus.subscribe(NotificationFailed, self.failed.append)

        self.service = NotificationService(
            router=NotificationRouter(lambda: ENABLED),
            dispatcher=NotificationDispatcher(self.channels, self.formatters),
            history=self.history,
            event_bus=self.bus,
        )


# ── Router ────────────────────────────────────────────────────────────────────


def _router() -> NotificationRouter:
    return NotificationRouter(lambda: ENABLED)


def test_router_info_goes_to_primary_channel_only() -> None:
    assert _router().route(Notification.create("t", "b", Severity.INFO)) == ("telegram",)


def test_router_critical_broadcasts_to_all_enabled() -> None:
    assert _router().route(Notification.create("t", "b", Severity.CRITICAL)) == ENABLED


def test_router_explicit_channels_intersected_with_enabled() -> None:
    n = Notification.create("t", "b", channels=("macos_native", "email"))
    assert _router().route(n) == ("macos_native",)  # email не включён


def test_router_no_enabled_channels() -> None:
    router = NotificationRouter(lambda: ())
    assert router.route(Notification.create("t", "b")) == ()


# ── Registries ────────────────────────────────────────────────────────────────


def test_channel_registry_register_and_get() -> None:
    registry = ChannelRegistry()
    channel = FakeChannel("email")
    registry.register(channel)
    assert registry.get("email") is channel
    assert registry.ids() == ("email",)
    assert registry.get("нет") is None


def test_channel_registry_duplicate_raises() -> None:
    registry = ChannelRegistry()
    registry.register(FakeChannel("email"))
    with pytest.raises(NotificationError):
        registry.register(FakeChannel("email"))


def test_formatter_registry_fallback_to_default() -> None:
    default = PlainTextFormatter()
    registry = FormatterRegistry(default=default)
    assert registry.get("незнакомый") is default

    custom = PlainTextFormatter()
    registry.register("email", custom)
    assert registry.get("email") is custom


# ── Dispatcher ────────────────────────────────────────────────────────────────


async def test_dispatcher_multi_channel_delivery() -> None:
    c = Center()
    n = Notification.create("Заголовок", "Тело", Severity.CRITICAL)

    report = await NotificationDispatcher(c.channels, c.formatters).dispatch(n, ENABLED)

    assert report.all_ok
    assert report.successful_channels == ENABLED
    assert report.trace_id == n.trace_id
    assert report.started_at is not None and report.finished_at is not None
    assert len(c.telegram.sent) == 1 and len(c.macos.sent) == 1


async def test_dispatcher_channel_failure_is_isolated() -> None:
    c = Center(macos_fails=True)
    n = Notification.create("З", "т")

    report = await NotificationDispatcher(c.channels, c.formatters).dispatch(n, ENABLED)

    assert report.delivered_any and not report.all_ok
    assert report.failed_channels == ("macos_native",)
    assert len(c.telegram.sent) == 1  # второй канал не пострадал


async def test_dispatcher_unknown_channel_reported() -> None:
    c = Center()
    report = await NotificationDispatcher(c.channels, c.formatters).dispatch(
        Notification.create("З", "т"), ("призрак",)
    )
    assert report.failed_channels == ("призрак",)
    assert "не зарегистрирован" in (report.results[0].error or "")


class _ExplodingChannel:
    channel_id = "boom"

    async def send(self, notification: Notification, text: str) -> DeliveryResult:
        raise RuntimeError("канал взорвался")


async def test_dispatcher_survives_channel_exception() -> None:
    channels = ChannelRegistry()
    channels.register(_ExplodingChannel())
    dispatcher = NotificationDispatcher(channels, FormatterRegistry(PlainTextFormatter()))

    report = await dispatcher.dispatch(Notification.create("З", "т"), ("boom",))

    assert not report.delivered_any
    assert "взорвался" in (report.results[0].error or "")


# ── Service: очередь, события, журнал ────────────────────────────────────────


async def test_service_queue_lifecycle_events_and_history() -> None:
    c = Center()
    n = Notification.create("Груз", "Москва → Казань", Severity.CRITICAL)

    await c.service.send(n)
    await c.service.flush()

    assert len(c.queued) == 1
    assert len(c.sending) == 1 and c.sending[0].channels == ENABLED
    assert len(c.delivered) == 1 and c.delivered[0].report.all_ok
    assert c.failed == []
    # журнал: одна итоговая запись с trace_id
    assert len(c.history.entries) == 1
    entry = c.history.entries[0]
    assert entry.kind is HistoryKind.NOTIFICATION
    assert entry.trace_id == n.trace_id
    assert "telegram" in entry.details
    await c.service.aclose()


async def test_service_total_failure_publishes_failed() -> None:
    c = Center(telegram_fails=True, macos_fails=True)
    n = Notification.create("З", "т", Severity.CRITICAL)

    await c.service.send(n)
    await c.service.flush()

    assert len(c.failed) == 1 and c.delivered == []
    entry = c.history.entries[0]
    assert entry.severity is Severity.WARNING
    assert "Не доставлено" in entry.details
    await c.service.aclose()


async def test_service_preserves_order() -> None:
    c = Center()
    for i in range(5):
        await c.service.send(Notification.create(f"N{i}", ""))
    await c.service.flush()

    assert [title for title, _ in c.telegram.sent] == [f"N{i}" for i in range(5)]
    await c.service.aclose()


async def test_service_concurrent_senders() -> None:
    c = Center()
    await asyncio.gather(
        *(c.service.send(Notification.create(f"C{i}", "", Severity.CRITICAL)) for i in range(10))
    )
    await c.service.flush()

    assert len(c.delivered) == 10
    assert len(c.telegram.sent) == 10 and len(c.macos.sent) == 10
    await c.service.aclose()


async def test_user_action_recorded_with_user_action_kind() -> None:
    c = Center()
    n = Notification.create(
        "Ручная отправка", "т", context=NotificationContext(source="manual", user_action=True)
    )
    await c.service.deliver_now(n)

    assert c.history.entries[0].kind is HistoryKind.USER_ACTION
    assert c.history.entries[0].source == "manual"


async def test_send_notification_command_full_path() -> None:
    c = Center()
    bus = CommandBus()
    bus.register(SendNotification, SendNotificationHandler(c.service))

    report = await bus.dispatch(
        SendNotification(title="Из команды", body="тело", severity=Severity.CRITICAL)
    )

    assert report.all_ok
    assert report.successful_channels == ENABLED
    assert len(c.history.entries) == 1
