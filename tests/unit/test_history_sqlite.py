"""Тесты SQLite-журнала: Database + SqliteHistoryRepository."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.core.clock import utc_now
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.severity import Severity
from app.infrastructure.storage.database import Database
from app.infrastructure.storage.history_repository import SqliteHistoryRepository


def _repo(tmp_path: Path) -> SqliteHistoryRepository:
    database = Database(tmp_path / "test.db")
    database.connect()
    return SqliteHistoryRepository(database)


def _entry(title: str, kind: HistoryKind = HistoryKind.NOTIFICATION) -> HistoryEntry:
    return HistoryEntry.create(
        kind, Severity.INFO, title, details="детали", source="test", trace_id="t-1"
    )


async def test_add_and_query_roundtrip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    entry = _entry("Первая запись")

    await repo.add(entry)
    loaded = await repo.query()

    assert len(loaded) == 1
    assert loaded[0] == entry  # полный roundtrip: id, время, kind, trace_id


async def test_query_filters_by_kind_and_orders_desc(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.add(_entry("A", HistoryKind.NOTIFICATION))
    await repo.add(_entry("B", HistoryKind.ERROR))
    await repo.add(_entry("C", HistoryKind.NOTIFICATION))

    notifications = await repo.query(kind=HistoryKind.NOTIFICATION)

    assert [e.title for e in notifications] == ["C", "A"]  # новые первыми


async def test_count_and_last(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.add(_entry("A"))
    await repo.add(_entry("B", HistoryKind.ERROR))

    assert await repo.count() == 2
    assert await repo.count(kind=HistoryKind.ERROR) == 1
    last = await repo.last()
    assert last is not None and last.title == "B"
    assert await repo.last(kind=HistoryKind.SOURCE_EVENT) is None


async def test_prune_removes_old_entries(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.add(_entry("Старая"))

    removed = await repo.prune(before=utc_now() + timedelta(seconds=1))

    assert removed == 1
    assert await repo.count() == 0


async def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Повторное открытие базы не ломает схему и данные."""
    path = tmp_path / "test.db"
    first = Database(path)
    first.connect()
    repo = SqliteHistoryRepository(first)
    await repo.add(_entry("Живучая"))
    first.close()

    second = Database(path)
    second.connect()  # миграции уже применены — не падает
    loaded = await SqliteHistoryRepository(second).query()
    assert [e.title for e in loaded] == ["Живучая"]
    second.close()
