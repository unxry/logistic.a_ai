"""SQLite-реализация NotificationHistoryRepository."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.models.notification_history import NotificationHistoryEntry, NotificationOpenState
from app.infrastructure.storage.database import Database


class SqliteNotificationHistoryRepository:
    """История уведомлений в SQLite."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def add(self, entry: NotificationHistoryEntry) -> None:
        """Добавить запись уведомления."""
        await asyncio.to_thread(
            self._db.execute,
            """
            INSERT OR IGNORE INTO notification_history (
                id, notification_id, occurred_at, type, source, route, profit, ai_score,
                open_state, cargo_id, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.notification_id,
                entry.occurred_at.isoformat(),
                entry.type,
                entry.source,
                entry.route,
                str(entry.profit) if entry.profit is not None else None,
                entry.ai_score,
                entry.open_state.value,
                entry.cargo_id,
                entry.trace_id,
            ),
        )

    async def query(
        self,
        *,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[NotificationHistoryEntry, ...]:
        """Выбрать уведомления (новые — первыми)."""
        sql = "SELECT * FROM notification_history"
        params: list[object] = []
        if since is not None:
            sql += " WHERE occurred_at >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY occurred_at DESC LIMIT ? OFFSET ?"
        rows = await asyncio.to_thread(self._db.query, sql, (*params, limit, offset))
        return tuple(self._to_entry(row) for row in rows)

    async def mark_opened(self, notification_id: str) -> None:
        """Отметить уведомление открытым пользователем."""
        await asyncio.to_thread(
            self._db.execute,
            "UPDATE notification_history SET open_state = ? WHERE notification_id = ?",
            (NotificationOpenState.OPENED.value, notification_id),
        )

    async def open_state(self, notification_id: str) -> NotificationOpenState:
        """Текущее состояние открытия уведомления."""
        rows = await asyncio.to_thread(
            self._db.query,
            "SELECT open_state FROM notification_history WHERE notification_id = ?",
            (notification_id,),
        )
        return (
            NotificationOpenState(str(rows[0]["open_state"]))
            if rows
            else NotificationOpenState.UNOPENED
        )

    @staticmethod
    def _to_entry(row: Any) -> NotificationHistoryEntry:
        profit = row["profit"]
        score = row["ai_score"]
        return NotificationHistoryEntry(
            id=str(row["id"]),
            notification_id=str(row["notification_id"]),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            type=str(row["type"]),
            source=str(row["source"]),
            route=str(row["route"]),
            profit=Decimal(str(profit)) if profit is not None else None,
            ai_score=int(score) if score is not None else None,
            open_state=NotificationOpenState(str(row["open_state"])),
            cargo_id=str(row["cargo_id"]),
            trace_id=str(row["trace_id"]),
        )
