"""События Scheduler Runtime (для Dashboard и журнала)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.scheduler import JobResult


@dataclass(frozen=True, slots=True)
class SchedulerStarted(Event):
    """Runtime запущен; несёт имена зарегистрированных задач."""

    job_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchedulerStopped(Event):
    """Runtime остановлен."""


@dataclass(frozen=True, slots=True)
class JobStarted(Event):
    """Запуск задачи начат."""

    job_name: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class JobCompleted(Event):
    """Задача выполнена успешно."""

    result: JobResult


@dataclass(frozen=True, slots=True)
class JobFailed(Event):
    """Задача завершилась ошибкой (после всех попыток)."""

    result: JobResult


@dataclass(frozen=True, slots=True)
class JobSkipped(Event):
    """Запуск пропущен (лимит параллельности и т.п.)."""

    job_name: str
    reason: str
    trace_id: str = ""
