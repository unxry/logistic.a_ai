"""SqliteMatchingRepository — решения подбора в SQLite (asyncio.to_thread)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.models.analytics import (
    DriverAnalytics,
    MatchingAnalytics,
    RouteAnalytics,
    summarize_decisions,
    summarize_routes,
)
from app.core.models.matching import MatchingDecision
from app.infrastructure.storage.database import Database


class SqliteMatchingRepository:
    """Реализация порта MatchingRepository."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def save_decision(self, decision: MatchingDecision) -> None:
        """Сохранить решение подбора."""
        await asyncio.to_thread(
            self._db.execute,
            "INSERT INTO matching_decisions (id, cargo_id, vehicle_profile_id, driver_id,"
            " score, profit, explanation, route, distance_km, selected, rejected_reason,"
            " trace_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.id,
                decision.cargo_id,
                decision.vehicle_profile_id,
                decision.driver_id,
                decision.score,
                str(decision.profit) if decision.profit is not None else None,
                "\n".join(decision.explanation),
                decision.route,
                decision.distance_km,
                1 if decision.selected else 0,
                decision.rejected_reason,
                decision.trace_id,
                decision.timestamp.isoformat(),
            ),
        )

    async def get_history(
        self, *, driver_id: str | None = None, limit: int = 100
    ) -> tuple[MatchingDecision, ...]:
        """История решений (новые первыми)."""
        sql = "SELECT * FROM matching_decisions"
        params: list[object] = []
        if driver_id is not None:
            sql += " WHERE driver_id = ?"
            params.append(driver_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = await asyncio.to_thread(self._db.query, sql, (*params, limit))
        return tuple(self._to_decision(row) for row in rows)

    async def get_statistics(self) -> MatchingAnalytics:
        """Сводная статистика (чистая агрегация ядра)."""
        return summarize_decisions(await self.get_history(limit=10_000))

    async def route_statistics(self) -> RouteAnalytics:
        """Маршрутная аналитика (чистая агрегация ядра)."""
        return summarize_routes(await self.get_history(limit=10_000))

    async def driver_statistics(self, driver_id: str) -> DriverAnalytics:
        """Метрики водителя."""
        decisions = await self.get_history(driver_id=driver_id, limit=10_000)
        selected = [d for d in decisions if d.selected]
        income = sum((d.profit for d in selected if d.profit is not None), start=Decimal(0))
        average = sum(d.score for d in decisions) / len(decisions) if decisions else 0.0
        return DriverAnalytics(
            driver_id=driver_id,
            searched_count=len(decisions),
            selected_count=len(selected),
            rejected_count=len(decisions) - len(selected),
            estimated_income=income,
            average_match_score=average,
        )

    @staticmethod
    def _to_decision(row: Any) -> MatchingDecision:
        explanation = tuple(part for part in str(row["explanation"]).split("\n") if part)
        profit_raw = row["profit"]
        distance_raw = row["distance_km"]
        return MatchingDecision(
            id=str(row["id"]),
            cargo_id=str(row["cargo_id"]),
            driver_id=str(row["driver_id"]),
            score=int(row["score"]),
            selected=bool(row["selected"]),
            rejected_reason=str(row["rejected_reason"]),
            vehicle_profile_id=str(row["vehicle_profile_id"]),
            profit=Decimal(str(profit_raw)) if profit_raw is not None else None,
            explanation=explanation,
            route=str(row["route"]),
            distance_km=float(distance_raw) if distance_raw is not None else None,
            trace_id=str(row["trace_id"]),
            timestamp=datetime.fromisoformat(str(row["created_at"])),
        )
