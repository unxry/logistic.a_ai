"""Порт хранилища грузов (кандидаты для поиска)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.core.models.cargo_workflow import (
    CargoWorkflowState,
    CargoWorkflowTransition,
)
from app.core.models.logistics.cargo import Cargo
from app.core.models.search import CargoSearchQuery


class CargoRepository(Protocol):
    """Хранилище грузов (in-memory сейчас, SQLite позже — за тем же портом)."""

    async def save(self, cargo: Cargo) -> None:
        """Сохранить/обновить груз (по id)."""
        ...

    async def save_many(self, cargos: Sequence[Cargo]) -> None:
        """Сохранить/обновить пачку грузов."""
        ...

    async def get(self, cargo_id: str) -> Cargo | None:
        """Груз по id; ``None`` — не найден."""
        ...

    async def search(self, query: CargoSearchQuery) -> Sequence[Cargo]:
        """Кандидаты под запрос (тонкая выборка; точный отбор — Search Engine)."""
        ...

    async def find_by_region(self, loading_region: str) -> Sequence[Cargo]:
        """Грузы с загрузкой в регионе."""
        ...

    async def workflow_state(self, cargo_id: str) -> CargoWorkflowState:
        """Текущий workflow-статус груза."""
        ...

    async def transition_workflow(self, transition: CargoWorkflowTransition) -> None:
        """Зафиксировать переход статуса и сделать его текущим."""
        ...

    async def workflow_history(self, cargo_id: str) -> Sequence[CargoWorkflowTransition]:
        """История переходов статуса груза (старые → новые)."""
        ...

    async def list_by_state(
        self,
        state: CargoWorkflowState,
        *,
        sort_by: str = "time",
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Cargo]:
        """Грузы в выбранном статусе: избранное, в работе, завершённые и т.п."""
        ...

    async def is_ignored_offer(self, cargo: Cargo) -> bool:
        """Скрыто ли именно это предложение груза (по fingerprint)."""
        ...

    async def count_today(self, source_id: str | None = None) -> int:
        """Сколько грузов сохранено сегодня."""
        ...
