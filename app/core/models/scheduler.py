"""Модели планировщика: состояния, политики запуска, spec, результат, метрики, контекст.

Job — это данные (JobSpec) + одна корутина run(context): благодаря этому
runtime можно заменить (asyncio → что угодно), не меняя ни одной задачи.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from logging import Logger
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.settings import AppSettings

if TYPE_CHECKING:
    # Только для типов: импорт модуля ports исполняет __init__ пакета,
    # который тянет events → models.scheduler — циклический импорт.
    from app.core.ports.history_repository import HistoryRepository
    from app.core.ports.notification_sender import NotificationSender


class JobState(Enum):
    """Состояние задачи в runtime."""

    IDLE = "idle"
    WAITING = "waiting"
    RUNNING = "running"
    FAILED = "failed"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class JobRetryPolicy:
    """Политика повторов задач (отдельная от транспортной Telegram).

    По умолчанию повторов нет: ретраи — осознанное решение автора задачи.
    """

    max_attempts: int = 1
    delay_seconds: float = 0.0
    backoff: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """Пауза перед следующей попыткой (attempt считается с 1)."""
        return self.delay_seconds * (self.backoff ** (attempt - 1))


class JobSchedule(Protocol):
    """Политика запуска: когда выполнять следующий раз."""

    def next_run_at(self, now: datetime, last_run: datetime | None) -> datetime | None:
        """Момент следующего запуска; ``None`` — больше не запускать."""
        ...


@dataclass(frozen=True, slots=True)
class RunOnce:
    """Один запуск через ``delay_seconds`` после старта."""

    delay_seconds: float = 0.0

    def next_run_at(self, now: datetime, last_run: datetime | None) -> datetime | None:
        """Первый вызов — время запуска; после выполнения — None."""
        if last_run is not None:
            return None
        return now + timedelta(seconds=self.delay_seconds)


@dataclass(frozen=True, slots=True)
class Interval:
    """Периодический запуск каждые ``seconds`` (+ джиттер против «толп»)."""

    seconds: float
    jitter_seconds: float = 0.0
    run_immediately: bool = True

    def next_run_at(self, now: datetime, last_run: datetime | None) -> datetime | None:
        """Первый запуск — сразу (или через интервал), далее от последнего."""
        if last_run is None:
            return now if self.run_immediately else now + self._step()
        return last_run + self._step()

    def _step(self) -> timedelta:
        jitter = random.uniform(0, self.jitter_seconds) if self.jitter_seconds > 0 else 0.0
        return timedelta(seconds=self.seconds + jitter)


@dataclass(frozen=True, slots=True)
class Cron:
    """Cron-выражение (заготовка: реализация на croniter при первом сценарии)."""

    expression: str

    def next_run_at(self, now: datetime, last_run: datetime | None) -> datetime | None:
        """Пока не реализовано — задача с Cron не должна регистрироваться."""
        raise NotImplementedError("Cron-расписание появится вместе с первым cron-сценарием")


@dataclass(frozen=True, slots=True)
class Adaptive:
    """Адаптивное расписание (заготовка: интервал подстраивается под активность)."""

    base_seconds: float = 60.0

    def next_run_at(self, now: datetime, last_run: datetime | None) -> datetime | None:
        """Пока не реализовано (ADR-0014)."""
        raise NotImplementedError("Adaptive-расписание появится вместе с мониторингом")


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Полное описание задачи — только данные.

    ``max_parallel_runs=1`` — повторный запуск при выполняющейся задаче
    пропускается (JobSkipped). ``timeout_seconds`` — watchdog: зависшая
    задача отменяется по таймауту.
    """

    name: str
    schedule: JobSchedule
    timeout_seconds: float | None = None
    retry: JobRetryPolicy = field(default_factory=JobRetryPolicy)
    max_parallel_runs: int = 1


@dataclass(frozen=True, slots=True)
class JobResult:
    """Итог одного запуска задачи."""

    job_name: str
    success: bool
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    trace_id: str
    error: str | None = None
    next_run: datetime | None = None
    attempts: int = 1


@dataclass(frozen=True, slots=True)
class JobMetrics:
    """Накопленные метрики задачи (неизменяемый снапшот)."""

    runs: int = 0
    failures: int = 0
    total_duration_ms: int = 0
    last_run: datetime | None = None
    next_run: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Доля успешных запусков (0.0, если запусков не было)."""
        if self.runs == 0:
            return 0.0
        return (self.runs - self.failures) / self.runs

    @property
    def average_duration_ms(self) -> float:
        """Средняя длительность запуска."""
        if self.runs == 0:
            return 0.0
        return self.total_duration_ms / self.runs


@dataclass(frozen=True, slots=True)
class JobContext:
    """Всё, что задача получает от runtime, — одним объектом.

    Задачи не импортируют сервисы: уведомления — через порт
    ``NotificationSender``, журнал — ``HistoryRepository``, настройки —
    провайдером. ``trace_id`` — корреляция текущего запуска (насквозь
    до уведомлений и журнала).
    """

    logger: Logger
    notifications: NotificationSender
    history: HistoryRepository
    settings: Callable[[], AppSettings]
    trace_factory: Callable[[], str] = lambda: uuid4().hex
    clock: Callable[[], datetime] = utc_now
    trace_id: str = ""
