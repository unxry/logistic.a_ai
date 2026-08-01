"""Тесты платформы источников: Registry, Runtime, здоровье, события, Scheduler."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime

import pytest

from app.buses import EventBus
from app.core.clock import utc_now
from app.core.errors import (
    DuplicateSourceError,
    SourceNetworkError,
    UnknownSourceError,
)
from app.core.events import (
    CargoReceived,
    SourceCompleted,
    SourceFailed,
    SourceHealthChanged,
    SourceRegistered,
    SourceStarted,
)
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.notification import Notification
from app.core.models.scheduler import Interval, JobRetryPolicy
from app.core.models.settings import AppSettings
from app.core.models.sources import (
    RawCargo,
    SourceCapabilities,
    SourceContext,
    SourceResult,
    SourceSpec,
    SourceStatus,
)
from app.services.scheduler import JobRegistry, SchedulerRuntime
from app.services.sources import CargoNormalizer, SourceRegistry, SourceRuntime


class StubSource:
    """Источник-фейк: управляемые ошибки, сон, содержимое."""

    def __init__(
        self,
        source_id: str = "demo",
        *,
        enabled: bool = True,
        fail_times: int = 0,
        sleep_seconds: float = 0.0,
        timeout: float | None = None,
        retry: JobRetryPolicy | None = None,
        items: int = 2,
    ) -> None:
        self.calls: list[str] = []
        self._fail_times = fail_times
        self._sleep = sleep_seconds
        self._items = items
        self._spec = SourceSpec(
            id=source_id,
            name=f"Источник {source_id}",
            enabled=enabled,
            capabilities=SourceCapabilities(supports_weight=True, supports_regions=True),
            schedule=Interval(seconds=999, run_immediately=False),
            timeout_seconds=timeout,
            retry_policy=retry if retry is not None else JobRetryPolicy(),
        )

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    async def fetch(self, context: SourceContext) -> SourceResult:
        self.calls.append(context.trace_id)
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise SourceNetworkError("сеть недоступна")
        raw = tuple(
            RawCargo(
                external_id=f"c{i}",
                title=f"Груз {i}",
                attributes={"weight": "5 тонн", "loading_region": "москва"},
            )
            for i in range(self._items)
        )
        return SourceResult(
            source_id=self._spec.id,
            received_at=utc_now(),
            raw_items=raw,
            trace_id=context.trace_id,
        )


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class InMemoryHistory:
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


class Rig:
    def __init__(self, *sources: StubSource) -> None:
        self.bus = EventBus()
        self.registry = SourceRegistry(self.bus)
        self.registered: list[SourceRegistered] = []
        self.bus.subscribe(SourceRegistered, self.registered.append)
        for source in sources:
            self.registry.register(source)

        self.sender = FakeSender()
        self.history = InMemoryHistory()
        self.started: list[SourceStarted] = []
        self.completed: list[SourceCompleted] = []
        self.failed: list[SourceFailed] = []
        self.health_changes: list[SourceHealthChanged] = []
        self.cargo: list[CargoReceived] = []
        self.bus.subscribe(SourceStarted, self.started.append)
        self.bus.subscribe(SourceCompleted, self.completed.append)
        self.bus.subscribe(SourceFailed, self.failed.append)
        self.bus.subscribe(SourceHealthChanged, self.health_changes.append)
        self.bus.subscribe(CargoReceived, self.cargo.append)

        self.runtime = SourceRuntime(
            registry=self.registry,
            normalizer=CargoNormalizer(),
            event_bus=self.bus,
            notifications=self.sender,
            history=self.history,
            settings_provider=AppSettings,
        )


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_register_remove_get() -> None:
    rig = Rig(StubSource("a"))
    assert rig.registry.ids() == ("a",)
    assert len(rig.registered) == 1 and rig.registered[0].source_id == "a"

    with pytest.raises(DuplicateSourceError):
        rig.registry.register(StubSource("a"))

    rig.registry.remove("a")
    assert rig.registry.ids() == ()
    with pytest.raises(UnknownSourceError):
        rig.registry.get("a")
    with pytest.raises(UnknownSourceError):
        rig.registry.remove("a")


# ── Runtime: успех ────────────────────────────────────────────────────────────


async def test_successful_run_normalizes_and_publishes() -> None:
    source = StubSource("demo", items=3)
    rig = Rig(source)

    report = await rig.runtime.run_source("demo")

    assert report.success and report.raw_count == 3 and len(report.items) == 3
    assert report.items[0].weight_kg == 5000  # нормализация сработала
    assert report.items[0].loading_region == "Москва"
    # события
    assert len(rig.started) == 1 and len(rig.completed) == 1
    assert rig.completed[0].items_count == 3
    assert len(rig.cargo) == 1 and len(rig.cargo[0].items) == 3
    assert rig.cargo[0].trace_id == report.trace_id
    # журнал
    entry = rig.history.entries[0]
    assert entry.kind is HistoryKind.SOURCE_EVENT
    assert "3" in entry.title and entry.trace_id == report.trace_id
    # здоровье и метрики
    assert rig.runtime.health("demo").status is SourceStatus.ONLINE
    assert rig.runtime.metrics("demo").total_cargo_received == 3


async def test_failure_after_retries_notifies_user() -> None:
    source = StubSource("ati", fail_times=99, retry=JobRetryPolicy(max_attempts=3))
    rig = Rig(source)

    report = await rig.runtime.run_source("ati")

    assert not report.success and report.attempts == 3
    assert len(source.calls) == 3  # ретраи были
    assert len(rig.failed) == 1 and "сеть" in rig.failed[0].error
    assert rig.runtime.health("ati").status is SourceStatus.FAILED
    # уведомление через Notification Center: имя, ошибка, попытки
    assert len(rig.sender.sent) == 1
    notification = rig.sender.sent[0]
    assert "Источник" in notification.title
    assert "3/3" in notification.body
    assert notification.trace_id == report.trace_id
    # журнал WARNING
    assert "Попыток: 3" in rig.history.entries[0].details


async def test_retry_recovers() -> None:
    source = StubSource("flaky", fail_times=1, retry=JobRetryPolicy(max_attempts=2))
    rig = Rig(source)

    report = await rig.runtime.run_source("flaky")

    assert report.success and report.attempts == 2
    assert rig.sender.sent == []  # успешный ретрай — не тревожим пользователя


async def test_timeout_is_failure() -> None:
    rig = Rig(StubSource("slow", sleep_seconds=1.0, timeout=0.02))

    report = await rig.runtime.run_source("slow")

    assert not report.success
    assert report.error is not None and "не ответил" in report.error


async def test_disabled_source_skipped() -> None:
    rig = Rig(StubSource("off", enabled=False))

    report = await rig.runtime.run_source("off")

    assert not report.success and report.error == "Источник выключен"
    assert rig.runtime.health("off").status is SourceStatus.DISABLED
    assert rig.started == [] and rig.sender.sent == []  # тихо: это не авария


async def test_degraded_health_after_mixed_runs() -> None:
    source = StubSource("shaky", fail_times=2)
    rig = Rig(source)

    await rig.runtime.run_source("shaky")  # fail
    await rig.runtime.run_source("shaky")  # fail
    report = await rig.runtime.run_source("shaky")  # success

    assert report.success
    health = rig.runtime.health("shaky")
    assert health.status is SourceStatus.DEGRADED  # rate 1/3 < 0.8
    assert health.last_success is not None
    statuses = [event.status for event in rig.health_changes]
    assert statuses == [SourceStatus.FAILED, SourceStatus.DEGRADED]


async def test_unknown_source_raises() -> None:
    rig = Rig()
    with pytest.raises(UnknownSourceError):
        await rig.runtime.run_source("призрак")


# ── Интеграция со Scheduler ──────────────────────────────────────────────────


async def test_scheduler_runs_source_via_job() -> None:
    """Полный поток: Scheduler → SourcePollJob → Runtime → Source → события."""
    source = StubSource("demo")
    rig = Rig(source)

    job_registry = JobRegistry()
    for job in rig.runtime.build_jobs():
        job_registry.register(job)
    scheduler = SchedulerRuntime(
        registry=job_registry,
        event_bus=rig.bus,
        notifications=rig.sender,
        history=rig.history,
        settings_provider=AppSettings,
    )

    result = await scheduler.run_now("source:demo")

    assert result is not None and result.success
    assert source.calls == [result.trace_id]  # trace job'а дошёл до источника
    assert len(rig.completed) == 1
    assert rig.runtime.health("demo").status is SourceStatus.ONLINE


def test_build_jobs_skips_disabled_sources() -> None:
    rig = Rig(StubSource("on"), StubSource("off", enabled=False))
    names = [job.spec.name for job in rig.runtime.build_jobs()]
    assert names == ["source:on"]
