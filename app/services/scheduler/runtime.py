"""SchedulerRuntime — единственный исполнитель фоновых задач.

Ответственность: жизненный цикл супервизоров (по одному на задачу),
исполнение с watchdog-таймаутом и ретраями (JobRetryPolicy), лимит
параллельности, метрики, журнал, события и уведомления об ошибках.

Runtime знает только порты ядра: Notification Center — через
``NotificationSender``, журнал — через ``HistoryRepository``. О Telegram
он не знает ничего.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from time import perf_counter
from uuid import uuid4

from app.core.clock import utc_now
from app.core.errors import StorageError
from app.core.events import (
    JobCompleted,
    JobFailed,
    JobSkipped,
    JobStarted,
    SchedulerStarted,
    SchedulerStopped,
)
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.scheduler import JobContext, JobMetrics, JobResult, JobState
from app.core.models.settings import AppSettings
from app.core.models.severity import Severity
from app.core.ports import EventPublisher, HistoryRepository, Job, NotificationSender
from app.services.scheduler.registry import JobRegistry

logger = logging.getLogger(__name__)

_SOURCE = "scheduler"


@dataclass(slots=True)
class _JobRuntime:
    """Изменяемое состояние задачи внутри runtime."""

    state: JobState = JobState.IDLE
    running_count: int = 0
    last_run: datetime | None = None
    metrics: JobMetrics = field(default_factory=JobMetrics)
    resume_gate: asyncio.Event = field(default_factory=asyncio.Event)


class SchedulerRuntime:
    """Исполнитель задач: супервизоры, watchdog, ретраи, метрики."""

    def __init__(
        self,
        *,
        registry: JobRegistry,
        event_bus: EventPublisher,
        notifications: NotificationSender,
        history: HistoryRepository,
        settings_provider: Callable[[], AppSettings],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._registry = registry
        self._events = event_bus
        self._notifications = notifications
        self._history = history
        self._settings_provider = settings_provider
        self._clock = clock

        self._runtimes: dict[str, _JobRuntime] = {}
        self._supervisors: dict[str, asyncio.Task[None]] = {}
        self._running = False

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Запущен ли runtime."""
        return self._running

    async def start(self) -> None:
        """Запустить супервизоры всех зарегистрированных задач."""
        if self._running:
            return
        self._running = True
        loop = asyncio.get_running_loop()
        for job in self._registry.all():
            runtime = self._runtime_of(job.spec.name)
            runtime.resume_gate.set()
            self._supervisors[job.spec.name] = loop.create_task(self._supervise(job))
        logger.info("Scheduler запущен: %d задач(и)", len(self._supervisors))
        self._events.publish(SchedulerStarted(job_names=self._registry.names()))

    async def stop(self) -> None:
        """Остановить супервизоры (graceful cancel)."""
        if not self._running:
            return
        self._running = False
        for task in self._supervisors.values():
            task.cancel()
        for task in self._supervisors.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._supervisors.clear()
        for runtime in self._runtimes.values():
            runtime.state = JobState.STOPPED
        logger.info("Scheduler остановлен")
        self._events.publish(SchedulerStopped())

    # ── Управление задачами ───────────────────────────────────────────────────

    def pause_job(self, name: str) -> None:
        """Приостановить задачу (текущий запуск не прерывается)."""
        self._registry.get(name)
        runtime = self._runtime_of(name)
        runtime.resume_gate.clear()
        runtime.state = JobState.PAUSED
        logger.info("Задача «%s» приостановлена", name)

    def resume_job(self, name: str) -> None:
        """Возобновить задачу."""
        self._registry.get(name)
        runtime = self._runtime_of(name)
        runtime.resume_gate.set()
        if runtime.state is JobState.PAUSED:
            runtime.state = JobState.IDLE
        logger.info("Задача «%s» возобновлена", name)

    async def run_now(self, name: str) -> JobResult | None:
        """Запустить немедленно (вне расписания; пауза не мешает ручному запуску)."""
        job = self._registry.get(name)
        return await self._execute(job)

    def job_state(self, name: str) -> JobState:
        """Состояние задачи."""
        return self._runtime_of(name).state

    def metrics(self, name: str) -> JobMetrics:
        """Метрики задачи."""
        return self._runtime_of(name).metrics

    # ── Исполнение ────────────────────────────────────────────────────────────

    async def _supervise(self, job: Job) -> None:
        """Цикл одной задачи: расписание → ожидание → запуск."""
        name = job.spec.name
        runtime = self._runtime_of(name)
        try:
            while True:
                await runtime.resume_gate.wait()
                now = self._clock()
                next_run = job.spec.schedule.next_run_at(now, runtime.last_run)
                runtime.metrics = replace(runtime.metrics, next_run=next_run)
                if next_run is None:
                    runtime.state = JobState.STOPPED
                    logger.info("Задача «%s»: расписание исчерпано", name)
                    return
                runtime.state = JobState.WAITING
                delay = max(0.0, (next_run - now).total_seconds())
                if delay > 0:
                    await asyncio.sleep(delay)
                if not runtime.resume_gate.is_set():
                    continue  # пауза наступила во время ожидания
                await self._execute(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            runtime.state = JobState.FAILED
            logger.exception("Супервизор задачи «%s» аварийно остановлен", name)

    async def _execute(self, job: Job) -> JobResult | None:
        """Один запуск: параллелизм → watchdog+ретраи → метрики/журнал/события."""
        spec = job.spec
        runtime = self._runtime_of(spec.name)

        if runtime.running_count >= spec.max_parallel_runs:
            logger.warning("Задача «%s»: запуск пропущен (уже выполняется)", spec.name)
            self._events.publish(
                JobSkipped(job_name=spec.name, reason="достигнут лимит параллельных запусков")
            )
            return None

        runtime.running_count += 1
        trace_id = uuid4().hex
        context = JobContext(
            logger=logging.getLogger(f"app.jobs.{spec.name}"),
            notifications=self._notifications,
            history=self._history,
            settings=self._settings_provider,
            trace_factory=lambda: uuid4().hex,
            clock=self._clock,
            trace_id=trace_id,
        )
        runtime.state = JobState.RUNNING
        logger.info("Задача «%s»: старт", spec.name)
        self._events.publish(JobStarted(job_name=spec.name, trace_id=trace_id))

        started_at = self._clock()
        started = perf_counter()
        error: str | None = None
        attempts = 0
        try:
            for attempt in range(1, spec.retry.max_attempts + 1):
                attempts = attempt
                try:
                    if spec.timeout_seconds is not None:
                        # Watchdog: зависшая задача отменяется по таймауту.
                        await asyncio.wait_for(job.run(context), timeout=spec.timeout_seconds)
                    else:
                        await job.run(context)
                    error = None
                    break
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    error = f"Задача превысила таймаут {spec.timeout_seconds} с"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                if attempt < spec.retry.max_attempts:
                    delay = spec.retry.delay_for(attempt)
                    logger.warning(
                        "Задача «%s»: попытка %d/%d не удалась, повтор через %.1f с",
                        spec.name,
                        attempt,
                        spec.retry.max_attempts,
                        delay,
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
        finally:
            runtime.running_count -= 1

        finished_at = self._clock()
        runtime.last_run = finished_at
        success = error is None
        next_run = spec.schedule.next_run_at(finished_at, runtime.last_run)
        result = JobResult(
            job_name=spec.name,
            success=success,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((perf_counter() - started) * 1000),
            trace_id=trace_id,
            error=error,
            next_run=next_run,
            attempts=attempts,
        )

        self._update_metrics(runtime, result)
        await self._record_history(result)

        if success:
            runtime.state = JobState.IDLE
            logger.info("Задача «%s»: успех за %d мс", spec.name, result.duration_ms)
            self._events.publish(JobCompleted(result=result))
        else:
            runtime.state = JobState.FAILED
            logger.warning("Задача «%s»: ошибка — %s", spec.name, error)
            self._events.publish(JobFailed(result=result))
            await self._notify_failure(result)
        return result

    # ── Вспомогательное ───────────────────────────────────────────────────────

    def _runtime_of(self, name: str) -> _JobRuntime:
        runtime = self._runtimes.get(name)
        if runtime is None:
            runtime = _JobRuntime()
            runtime.resume_gate.set()
            self._runtimes[name] = runtime
        return runtime

    @staticmethod
    def _update_metrics(runtime: _JobRuntime, result: JobResult) -> None:
        metrics = runtime.metrics
        runtime.metrics = replace(
            metrics,
            runs=metrics.runs + 1,
            failures=metrics.failures + (0 if result.success else 1),
            total_duration_ms=metrics.total_duration_ms + result.duration_ms,
            last_run=result.finished_at,
            next_run=result.next_run,
        )

    async def _record_history(self, result: JobResult) -> None:
        entry = HistoryEntry.create(
            kind=HistoryKind.SYSTEM_EVENT,
            severity=Severity.INFO if result.success else Severity.WARNING,
            title=f"Задача «{result.job_name}»: {'успех' if result.success else 'ошибка'}",
            details=(
                f"{result.duration_ms} мс, попыток: {result.attempts}"
                + (f". {result.error}" if result.error else "")
            ),
            source=_SOURCE,
            trace_id=result.trace_id,
        )
        try:
            await self._history.add(entry)
        except StorageError:
            logger.exception("Не удалось записать запуск задачи в журнал")

    async def _notify_failure(self, result: JobResult) -> None:
        """Об ошибке пользователь узнаёт через Notification Center."""
        notification = (
            NotificationBuilder()
            .title(f"Задача «{result.job_name}» завершилась ошибкой")
            .body(result.error or "")
            .severity(Severity.WARNING)
            .category(NotificationCategory.SYSTEM)
            .source(_SOURCE)
            .module(result.job_name)
            .trace_id(result.trace_id)
            .build()
        )
        try:
            await self._notifications.send(notification)
        except Exception:
            logger.exception("Не удалось отправить уведомление об ошибке задачи")
