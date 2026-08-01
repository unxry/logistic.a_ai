"""SqliteHistoryRepository — реализация порта HistoryRepository.

Все вызовы уходят в ``asyncio.to_thread``: sqlite3 синхронный, петля
qasync не блокируется.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.severity import Severity
from app.infrastructure.storage.database import Database


class SqliteHistoryRepository:
    """Журнал событий в SQLite."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def add(self, entry: HistoryEntry) -> None:
        """Добавить запись."""
        await asyncio.to_thread(
            self._db.execute,
            "INSERT INTO history (id, occurred_at, kind, severity, title, details, source,"
            " trace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.occurred_at.isoformat(),
                entry.kind.value,
                entry.severity.value,
                entry.title,
                entry.details,
                entry.source,
                entry.trace_id,
            ),
        )

    async def query(
        self,
        *,
        kind: HistoryKind | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[HistoryEntry]:
        """Выбрать записи (новые — первыми)."""
        sql, params = self._filtered("SELECT * FROM history", kind=kind, since=since)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        rows = await asyncio.to_thread(self._db.query, sql, (*params, limit))
        return tuple(self._to_entry(row) for row in rows)

    async def count(
        self,
        *,
        kind: HistoryKind | None = None,
        since: datetime | None = None,
    ) -> int:
        """Посчитать записи по фильтру."""
        sql, params = self._filtered("SELECT COUNT(*) AS n FROM history", kind=kind, since=since)
        rows = await asyncio.to_thread(self._db.query, sql, params)
        return int(rows[0]["n"]) if rows else 0

    async def last(self, *, kind: HistoryKind | None = None) -> HistoryEntry | None:
        """Последняя запись по фильтру."""
        entries = await self.query(kind=kind, limit=1)
        return entries[0] if entries else None

    async def prune(self, *, before: datetime) -> int:
        """Удалить записи старше порога; вернуть число удалённых."""
        return await asyncio.to_thread(
            self._db.execute,
            "DELETE FROM history WHERE occurred_at < ?",
            (before.isoformat(),),
        )

    @staticmethod
    def _filtered(
        base_sql: str, *, kind: HistoryKind | None, since: datetime | None
    ) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        if since is not None:
            clauses.append("occurred_at >= ?")
            params.append(since.isoformat())
        if clauses:
            base_sql += " WHERE " + " AND ".join(clauses)
        return base_sql, tuple(params)

    @staticmethod
    def _to_entry(row: Any) -> HistoryEntry:
        return HistoryEntry(
            id=str(row["id"]),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            kind=HistoryKind(row["kind"]),
            severity=Severity(row["severity"]),
            title=str(row["title"]),
            details=str(row["details"]),
            source=str(row["source"]),
            trace_id=str(row["trace_id"]),
        )
