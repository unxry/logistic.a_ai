"""Порт журнала событий (истории)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.core.models.history import HistoryEntry, HistoryKind


class HistoryRepository(Protocol):
    """Хранилище записей журнала (реализация: SQLite, WAL).

    Порт асинхронный: адаптер сам решает, как не блокировать петлю
    (``asyncio.to_thread`` для sqlite3).
    """

    async def add(self, entry: HistoryEntry) -> None:
        """Добавить запись."""
        ...

    async def query(
        self,
        *,
        kind: HistoryKind | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[HistoryEntry]:
        """Выбрать записи (новые — первыми)."""
        ...

    async def count(
        self,
        *,
        kind: HistoryKind | None = None,
        since: datetime | None = None,
    ) -> int:
        """Посчитать записи по фильтру."""
        ...

    async def last(self, *, kind: HistoryKind | None = None) -> HistoryEntry | None:
        """Последняя запись по фильтру."""
        ...

    async def prune(self, *, before: datetime) -> int:
        """Удалить записи старше порога; вернуть число удалённых."""
        ...
