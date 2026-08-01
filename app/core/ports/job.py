"""Порт фоновой задачи планировщика."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models.scheduler import JobContext, JobSpec


@runtime_checkable
class Job(Protocol):
    """Фоновая задача: описание (данные) + одна корутина.

    Контракт в ядре, чтобы задачи объявляли и плагины. Всё поведение
    runtime (расписание, таймаут, ретраи, параллелизм) описывается
    данными ``JobSpec`` — поэтому исполнитель заменяем, а задача
    переиспользуема без изменений (ADR-0014).
    Реализация обязана быть идемпотентной; исключения ловит runtime.
    """

    @property
    def spec(self) -> JobSpec:
        """Описание задачи."""
        ...

    async def run(self, context: JobContext) -> None:
        """Выполнить задачу (все зависимости — в контексте)."""
        ...
