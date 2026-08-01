"""Команды управления Scheduler Runtime."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.commands.base import Command
from app.core.models.scheduler import JobResult


@dataclass(frozen=True, slots=True)
class StartScheduler(Command[None]):
    """Запустить runtime (супервизоры всех зарегистрированных задач)."""


@dataclass(frozen=True, slots=True)
class StopScheduler(Command[None]):
    """Остановить runtime (отмена супервизоров)."""


@dataclass(frozen=True, slots=True)
class PauseJob(Command[None]):
    """Приостановить задачу по имени."""

    job_name: str


@dataclass(frozen=True, slots=True)
class ResumeJob(Command[None]):
    """Возобновить задачу по имени."""

    job_name: str


@dataclass(frozen=True, slots=True)
class RunJobNow(Command[JobResult | None]):
    """Запустить задачу немедленно; None — запуск пропущен (лимит параллельности)."""

    job_name: str
