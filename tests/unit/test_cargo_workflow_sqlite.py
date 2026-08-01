from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.models.cargo_workflow import CargoWorkflowAction, CargoWorkflowState
from app.core.models.history import HistoryEntry
from app.core.models.logistics.cargo import Cargo
from app.core.models.search import CargoSearchQuery
from app.infrastructure.storage import Database, SqliteCargoRepository
from app.services.logistics import CargoWorkflowService


class _History:
    def __init__(self) -> None:
        self.titles: list[str] = []

    async def add(self, entry: HistoryEntry) -> None:
        self.titles.append(entry.title)


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _cargo(cargo_id: str = "cargo-1", *, price: int = 100_000) -> Cargo:
    return Cargo(
        id=cargo_id,
        source_id="ati",
        title="Москва → Казань",
        loading_region="Москва",
        unloading_region="Казань",
        payment_amount=Decimal(price),
        distance_km=820,
    )


@pytest.mark.asyncio
async def test_sqlite_cargo_repository_keeps_workflow_history(tmp_path) -> None:
    database = Database(tmp_path / "logistai.db")
    database.connect()
    repository = SqliteCargoRepository(database)
    await repository.save(_cargo())

    history = _History()
    events = _Events()
    service = CargoWorkflowService(repository=repository, history=history, events=events)
    transition = await service.transition("cargo-1", CargoWorkflowAction.FAVORITE)

    assert transition.to_state is CargoWorkflowState.FAVORITE
    assert await repository.workflow_state("cargo-1") is CargoWorkflowState.FAVORITE
    assert [item.to_state for item in await repository.workflow_history("cargo-1")] == [
        CargoWorkflowState.NEW,
        CargoWorkflowState.FAVORITE,
    ]
    assert history.titles[-1] == "Груз добавлен в избранное"
    assert type(events.events[-1]).__name__ == "CargoFavorited"
    database.close()


@pytest.mark.asyncio
async def test_ignored_offer_is_hidden_until_offer_changes(tmp_path) -> None:
    database = Database(tmp_path / "logistai.db")
    database.connect()
    repository = SqliteCargoRepository(database)
    query = CargoSearchQuery.create("vehicle-1")

    await repository.save(_cargo(price=100_000))
    service = CargoWorkflowService(repository=repository, history=_History(), events=_Events())
    await service.transition("cargo-1", CargoWorkflowAction.IGNORE)
    assert await repository.search(query) == ()

    await repository.save(_cargo(price=120_000))
    assert [cargo.id for cargo in await repository.search(query)] == ["cargo-1"]
    database.close()
