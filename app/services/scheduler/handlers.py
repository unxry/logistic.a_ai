"""Обработчики команд Scheduler Runtime (регистрируются в bootstrap)."""

from __future__ import annotations

from app.core.commands import PauseJob, ResumeJob, RunJobNow, StartScheduler, StopScheduler
from app.core.models.scheduler import JobResult
from app.services.scheduler.runtime import SchedulerRuntime


class StartSchedulerHandler:
    """StartScheduler → запуск runtime."""

    def __init__(self, runtime: SchedulerRuntime) -> None:
        self._runtime = runtime

    async def __call__(self, command: StartScheduler) -> None:
        """Запустить супервизоры задач."""
        await self._runtime.start()


class StopSchedulerHandler:
    """StopScheduler → остановка runtime."""

    def __init__(self, runtime: SchedulerRuntime) -> None:
        self._runtime = runtime

    async def __call__(self, command: StopScheduler) -> None:
        """Остановить супервизоры задач."""
        await self._runtime.stop()


class PauseJobHandler:
    """PauseJob → приостановка задачи."""

    def __init__(self, runtime: SchedulerRuntime) -> None:
        self._runtime = runtime

    async def __call__(self, command: PauseJob) -> None:
        """Приостановить задачу по имени."""
        self._runtime.pause_job(command.job_name)


class ResumeJobHandler:
    """ResumeJob → возобновление задачи."""

    def __init__(self, runtime: SchedulerRuntime) -> None:
        self._runtime = runtime

    async def __call__(self, command: ResumeJob) -> None:
        """Возобновить задачу по имени."""
        self._runtime.resume_job(command.job_name)


class RunJobNowHandler:
    """RunJobNow → немедленный запуск с результатом."""

    def __init__(self, runtime: SchedulerRuntime) -> None:
        self._runtime = runtime

    async def __call__(self, command: RunJobNow) -> JobResult | None:
        """Запустить задачу немедленно; None — пропуск по параллельности."""
        return await self._runtime.run_now(command.job_name)
