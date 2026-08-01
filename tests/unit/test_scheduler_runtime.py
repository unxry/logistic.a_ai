"""Тесты SchedulerRuntime: реестр, исполнение, watchdog, ретраи, метрики, команды."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest

from app.buses import CommandBus, EventBus
from app.core.commands import PauseJob, ResumeJob, RunJobNow, StartScheduler, StopScheduler
from app.core.errors import DuplicateJobError, UnknownJobError
from app.core.events import (
    JobCompleted,
    JobFailed,
    JobSkipped,
    JobStarted,
    SchedulerStarted,
    SchedulerStopped,
)
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.notification import Notification
from app.core.models.scheduler import (
    Interval,
    JobContext,
    JobRetryPolicy,
    JobSchedule,
    JobSpec,
    JobState,
    RunOnce,
)
from app.core.models.settings import AppSettings
from app.services.scheduler import (
    HistoryCleanupJob,
    JobRegistry,
    PauseJobHandler,
    ResumeJobHandler,
    RunJobNowHandler,
    SchedulerRuntime,
    StartSchedulerHandler,
    StopSchedulerHandler,
)


class SpyJob:
    """Задача-шпион: считает запуски, умеет падать и спать."""

    def __init__(
        self,
        name: str = "spy",
        *,
        schedule: JobSchedule | None = None,
        fail_times: int = 0,
        sleep_seconds: float = 0.0,
        timeout: float | None = None,
        retry: JobRetryPolicy | None = None,
        max_parallel: int = 1,
    ) -> None:
        self.calls: list[str] = []
        self._fail_times = fail_times
        self._sleep = sleep_seconds
        self._spec = JobSpec(
            name=name,
            schedule=schedule if schedule is not None else RunOnce(),
            timeout_seconds=timeout,
            retry=retry if retry is not None else JobRetryPolicy(),
            max_parallel_runs=max_parallel,
        )

    @property
    def spec(self) -> JobSpec:
        return self._spec

    async def run(self, context: JobContext) -> None:
        self.calls.append(context.trace_id)
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("боевая ошибка")


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class InMemoryHistory:
    def __init__(self) -> None:
        self.entries: list[HistoryEntry] = []
        self.pruned_before: datetime | None = None

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
        self.pruned_before = before
        return 7


class Rig:
    """Собранный runtime на фейках + коллекторы событий."""

    def __init__(self, *jobs: SpyJob) -> None:
        self.registry = JobRegistry()
        for job in jobs:
            self.registry.register(job)
        self.bus = EventBus()
        self.sender = FakeSender()
        self.history = InMemoryHistory()

        self.started: list[JobStarted] = []
        self.completed: list[JobCompleted] = []
        self.failed: list[JobFailed] = []
        self.skipped: list[JobSkipped] = []
        self.sched_started: list[SchedulerStarted] = []
        self.sched_stopped: list[SchedulerStopped] = []
        self.bus.subscribe(JobStarted, self.started.append)
        self.bus.subscribe(JobCompleted, self.completed.append)
        self.bus.subscribe(JobFailed, self.failed.append)
        self.bus.subscribe(JobSkipped, self.skipped.append)
        self.bus.subscribe(SchedulerStarted, self.sched_started.append)
        self.bus.subscribe(SchedulerStopped, self.sched_stopped.append)

        self.runtime = SchedulerRuntime(
            registry=self.registry,
            event_bus=self.bus,
            notifications=self.sender,
            history=self.history,
            settings_provider=AppSettings,
        )


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_duplicate_and_unknown() -> None:
    registry = JobRegistry()
    registry.register(SpyJob("a"))
    with pytest.raises(DuplicateJobError):
        registry.register(SpyJob("a"))
    with pytest.raises(UnknownJobError):
        registry.get("нет")
    assert registry.names() == ("a",)


# ── RunNow, история, события, метрики ────────────────────────────────────────


async def test_run_now_success_records_everything() -> None:
    job = SpyJob("greet")
    rig = Rig(job)

    result = await rig.runtime.run_now("greet")

    assert result is not None and result.success
    assert job.calls == [result.trace_id]  # trace дошёл до задачи
    assert [e.job_name for e in rig.started] == ["greet"]
    assert len(rig.completed) == 1
    assert rig.runtime.job_state("greet") is JobState.IDLE
    # журнал
    entry = rig.history.entries[0]
    assert entry.kind is HistoryKind.SYSTEM_EVENT
    assert entry.trace_id == result.trace_id
    # метрики
    metrics = rig.runtime.metrics("greet")
    assert metrics.runs == 1 and metrics.failures == 0 and metrics.success_rate == 1.0


async def test_failure_notifies_user_and_marks_failed() -> None:
    rig = Rig(SpyJob("broken", fail_times=1))

    result = await rig.runtime.run_now("broken")

    assert result is not None and not result.success
    assert len(rig.failed) == 1
    assert rig.runtime.job_state("broken") is JobState.FAILED
    assert rig.runtime.metrics("broken").failures == 1
    # уведомление через Notification Center (порт), с корреляцией
    assert len(rig.sender.sent) == 1
    notification = rig.sender.sent[0]
    assert "broken" in notification.title
    assert notification.trace_id == result.trace_id
    # журнал: WARNING с текстом ошибки
    assert "боевая ошибка" in rig.history.entries[0].details


async def test_retry_recovers_after_failures() -> None:
    job = SpyJob("flaky", fail_times=2, retry=JobRetryPolicy(max_attempts=3))
    rig = Rig(job)

    result = await rig.runtime.run_now("flaky")

    assert result is not None and result.success
    assert result.attempts == 3
    assert len(job.calls) == 3
    assert rig.failed == []  # после успешного ретрая — не ошибка


async def test_watchdog_timeout_cancels_hung_job() -> None:
    rig = Rig(SpyJob("hung", sleep_seconds=1.0, timeout=0.02))

    result = await rig.runtime.run_now("hung")

    assert result is not None and not result.success
    assert result.error is not None and "таймаут" in result.error
    assert len(rig.failed) == 1


async def test_concurrency_limit_skips_second_run() -> None:
    job = SpyJob("busy", sleep_seconds=0.1)
    rig = Rig(job)

    first = asyncio.ensure_future(rig.runtime.run_now("busy"))
    await asyncio.sleep(0.02)  # первый запуск уже выполняется
    second = await rig.runtime.run_now("busy")

    assert second is None  # пропущен по лимиту
    assert len(rig.skipped) == 1 and rig.skipped[0].job_name == "busy"
    first_result = await first
    assert first_result is not None and first_result.success
    assert len(job.calls) == 1


async def test_unknown_job_run_now_raises() -> None:
    rig = Rig()
    with pytest.raises(UnknownJobError):
        await rig.runtime.run_now("призрак")


# ── Расписание, пауза, остановка ─────────────────────────────────────────────


async def test_interval_job_runs_repeatedly() -> None:
    job = SpyJob("tick", schedule=Interval(seconds=0.02))
    rig = Rig(job)

    await rig.runtime.start()
    await asyncio.sleep(0.09)
    await rig.runtime.stop()

    assert len(job.calls) >= 2  # выполнился несколько раз
    assert len(rig.sched_started) == 1 and len(rig.sched_stopped) == 1
    assert rig.runtime.job_state("tick") is JobState.STOPPED


async def test_run_once_schedule_finishes_supervisor() -> None:
    job = SpyJob("once", schedule=RunOnce())
    rig = Rig(job)

    await rig.runtime.start()
    await asyncio.sleep(0.05)

    assert len(job.calls) == 1
    assert rig.runtime.job_state("once") is JobState.STOPPED  # расписание исчерпано
    await rig.runtime.stop()


async def test_pause_and_resume() -> None:
    job = SpyJob("pausable", schedule=Interval(seconds=0.03, run_immediately=False))
    rig = Rig(job)

    await rig.runtime.start()
    rig.runtime.pause_job("pausable")
    assert rig.runtime.job_state("pausable") is JobState.PAUSED
    await asyncio.sleep(0.08)
    assert job.calls == []  # на паузе не выполнялась

    rig.runtime.resume_job("pausable")
    await asyncio.sleep(0.08)
    assert len(job.calls) >= 1  # после resume работает

    await rig.runtime.stop()


async def test_stop_cancels_waiting_jobs_cleanly() -> None:
    rig = Rig(SpyJob("slowpoke", schedule=Interval(seconds=999, run_immediately=False)))

    await rig.runtime.start()
    await rig.runtime.stop()  # не зависает и не бросает

    assert not rig.runtime.is_running
    assert len(rig.sched_stopped) == 1


# ── Команды через CommandBus ─────────────────────────────────────────────────


async def test_scheduler_commands_full_path() -> None:
    rig = Rig(SpyJob("cmd", schedule=Interval(seconds=999, run_immediately=False)))
    bus = CommandBus()
    bus.register(StartScheduler, StartSchedulerHandler(rig.runtime))
    bus.register(StopScheduler, StopSchedulerHandler(rig.runtime))
    bus.register(PauseJob, PauseJobHandler(rig.runtime))
    bus.register(ResumeJob, ResumeJobHandler(rig.runtime))
    bus.register(RunJobNow, RunJobNowHandler(rig.runtime))

    await bus.dispatch(StartScheduler())
    assert rig.runtime.is_running

    result = await bus.dispatch(RunJobNow(job_name="cmd"))
    assert result is not None and result.success

    await bus.dispatch(PauseJob(job_name="cmd"))
    assert rig.runtime.job_state("cmd") is JobState.PAUSED
    await bus.dispatch(ResumeJob(job_name="cmd"))
    assert rig.runtime.job_state("cmd") is not JobState.PAUSED

    await bus.dispatch(StopScheduler())
    assert not rig.runtime.is_running


# ── Встроенная задача ────────────────────────────────────────────────────────


async def test_history_cleanup_job_prunes_by_retention() -> None:
    rig = Rig()
    job = HistoryCleanupJob()
    rig.registry.register(job)

    result = await rig.runtime.run_now("history_cleanup")

    assert result is not None and result.success
    assert rig.history.pruned_before is not None
    # порог = now - retention (90 дней по умолчанию), проверяем с допуском
    expected = 90
    delta = result.finished_at - rig.history.pruned_before
    assert timedelta(days=expected - 1) < delta < timedelta(days=expected + 1)
