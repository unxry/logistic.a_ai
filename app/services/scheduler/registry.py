"""Реестр задач планировщика.

Регистрация без if-ов: ``registry.register(job)`` (bootstrap или плагин
через PluginExtensions.add_job).
"""

from __future__ import annotations

from app.core.errors import DuplicateJobError, UnknownJobError
from app.core.ports import Job


class JobRegistry:
    """Именованный реестр задач."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def register(self, job: Job) -> None:
        """Зарегистрировать задачу; повторное имя — ошибка (признак бага)."""
        name = job.spec.name
        if name in self._jobs:
            raise DuplicateJobError(name)
        self._jobs[name] = job

    def get(self, name: str) -> Job:
        """Задача по имени; неизвестное имя — ошибка."""
        job = self._jobs.get(name)
        if job is None:
            raise UnknownJobError(name)
        return job

    def names(self) -> tuple[str, ...]:
        """Имена всех зарегистрированных задач."""
        return tuple(self._jobs)

    def all(self) -> tuple[Job, ...]:
        """Все зарегистрированные задачи."""
        return tuple(self._jobs.values())
