"""InMemoryCargoRepository — грузы в памяти (SQLite позже, за тем же портом)."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.models.cargo_identity import cargo_offer_fingerprint
from app.core.models.cargo_workflow import (
    CargoWorkflowState,
    CargoWorkflowTransition,
)
from app.core.models.logistics.cargo import Cargo
from app.core.models.search import CargoSearchQuery


class InMemoryCargoRepository:
    """Реализация порта CargoRepository в памяти процесса."""

    def __init__(self) -> None:
        self._cargos: dict[str, Cargo] = {}
        self._states: dict[str, CargoWorkflowState] = {}
        self._history: dict[str, list[CargoWorkflowTransition]] = {}
        self._ignored: set[tuple[str, str]] = set()

    async def save(self, cargo: Cargo) -> None:
        """Сохранить/обновить груз (по id)."""
        self._cargos[cargo.id] = cargo
        self._states.setdefault(cargo.id, CargoWorkflowState.NEW)

    async def save_many(self, cargos: Sequence[Cargo]) -> None:
        """Сохранить/обновить пачку грузов."""
        for cargo in cargos:
            await self.save(cargo)

    async def get(self, cargo_id: str) -> Cargo | None:
        """Груз по id."""
        return self._cargos.get(cargo_id)

    async def search(self, query: CargoSearchQuery) -> Sequence[Cargo]:
        """Все кандидаты (точный отбор — забота Search Engine)."""
        return tuple(
            cargo
            for cargo in self._cargos.values()
            if (cargo.id, cargo_offer_fingerprint(cargo)) not in self._ignored
        )

    async def find_by_region(self, loading_region: str) -> Sequence[Cargo]:
        """Грузы с загрузкой в регионе."""
        return tuple(
            cargo for cargo in self._cargos.values() if cargo.loading_region == loading_region
        )

    async def workflow_state(self, cargo_id: str) -> CargoWorkflowState:
        """Текущий workflow-статус груза."""
        return self._states.get(cargo_id, CargoWorkflowState.NEW)

    async def transition_workflow(self, transition: CargoWorkflowTransition) -> None:
        """Зафиксировать переход статуса и сделать его текущим."""
        self._states[transition.cargo_id] = transition.to_state
        self._history.setdefault(transition.cargo_id, []).append(transition)
        if transition.to_state is CargoWorkflowState.IGNORED:
            cargo = self._cargos.get(transition.cargo_id)
            fingerprint = (
                transition.offer_fingerprint
                if transition.offer_fingerprint
                else (cargo_offer_fingerprint(cargo) if cargo is not None else "")
            )
            self._ignored.add((transition.cargo_id, fingerprint))

    async def workflow_history(self, cargo_id: str) -> Sequence[CargoWorkflowTransition]:
        """История переходов статуса груза."""
        return tuple(self._history.get(cargo_id, ()))

    async def list_by_state(
        self,
        state: CargoWorkflowState,
        *,
        sort_by: str = "time",
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Cargo]:
        """Грузы в выбранном статусе."""
        items = [cargo for cargo in self._cargos.values() if self._states.get(cargo.id) is state]
        if sort_by == "distance":
            items.sort(
                key=lambda cargo: cargo.distance_km if cargo.distance_km is not None else 10**9
            )
        elif sort_by == "profit":
            items.sort(
                key=lambda cargo: cargo.payment_amount if cargo.payment_amount is not None else 0,
                reverse=True,
            )
        else:
            items.sort(key=lambda cargo: cargo.created_at, reverse=True)
        return tuple(items[offset : offset + limit])

    async def is_ignored_offer(self, cargo: Cargo) -> bool:
        """Скрыто ли именно это предложение груза."""
        return (cargo.id, cargo_offer_fingerprint(cargo)) in self._ignored

    async def count_today(self, source_id: str | None = None) -> int:
        """Сколько грузов сохранено сегодня."""
        if source_id is None:
            return len(self._cargos)
        return sum(1 for cargo in self._cargos.values() if cargo.source_id == source_id)
