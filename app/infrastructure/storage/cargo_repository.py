"""SqliteCargoRepository — постоянное хранилище всех найденных грузов."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.core.models.cargo_identity import cargo_offer_fingerprint
from app.core.models.cargo_workflow import (
    CargoWorkflowAction,
    CargoWorkflowState,
    CargoWorkflowTransition,
)
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.vehicle_profile import BodyType
from app.core.models.search import CargoSearchQuery
from app.infrastructure.storage.database import Database

_DEFAULT_SORT = "time"
_SORT_SQL: dict[str, str] = {
    "time": "created_at DESC",
    "profit": "CAST(COALESCE(payment_amount, '0') AS REAL) DESC",
    "ai_score": "created_at DESC",  # AI Score хранится в matching_decisions; safe fallback.
    "distance": "COALESCE(distance_km, 999999999) ASC",
}


class SqliteCargoRepository:
    """CargoRepository на SQLite: грузы, workflow, избранное и blacklist."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, cargo: Cargo) -> None:
        """Сохранить/обновить груз (по id)."""
        await self.save_many((cargo,))

    async def save_many(self, cargos: Sequence[Cargo]) -> None:
        """Сохранить/обновить пачку грузов в одной фоновой операции."""
        if not cargos:
            return
        await asyncio.to_thread(self._save_many_sync, tuple(cargos))

    async def get(self, cargo_id: str) -> Cargo | None:
        """Груз по id."""
        rows = await asyncio.to_thread(
            self._db.query, "SELECT * FROM cargos WHERE id = ?", (cargo_id,)
        )
        return self._to_cargo(rows[0]) if rows else None

    async def search(self, query: CargoSearchQuery) -> Sequence[Cargo]:
        """Кандидаты под запрос; ignored-offer fingerprint исключается."""
        clauses = [
            "NOT EXISTS ("
            "SELECT 1 FROM ignored_offers i "
            "WHERE i.cargo_id = cargos.id AND i.offer_fingerprint = cargos.offer_fingerprint"
            ")"
        ]
        params: list[object] = []
        if query.regions:
            placeholders = ", ".join("?" for _ in query.regions)
            clauses.append(f"loading_region IN ({placeholders})")
            params.extend(query.regions)
        if query.min_price is not None:
            clauses.append("CAST(payment_amount AS REAL) >= ?")
            params.append(str(query.min_price))
        if query.max_distance_km is not None:
            clauses.append("(distance_km IS NULL OR distance_km <= ?)")
            params.append(query.max_distance_km)
        sql = "SELECT * FROM cargos WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT 5000"
        rows = await asyncio.to_thread(self._db.query, sql, tuple(params))
        return tuple(self._to_cargo(row) for row in rows)

    async def find_by_region(self, loading_region: str) -> Sequence[Cargo]:
        """Грузы с загрузкой в регионе."""
        rows = await asyncio.to_thread(
            self._db.query,
            "SELECT * FROM cargos WHERE loading_region = ? ORDER BY created_at DESC LIMIT 1000",
            (loading_region,),
        )
        return tuple(self._to_cargo(row) for row in rows)

    async def workflow_state(self, cargo_id: str) -> CargoWorkflowState:
        """Текущий workflow-статус груза."""
        rows = await asyncio.to_thread(
            self._db.query, "SELECT workflow_state FROM cargos WHERE id = ?", (cargo_id,)
        )
        if not rows:
            return CargoWorkflowState.NEW
        return CargoWorkflowState(str(rows[0]["workflow_state"]))

    async def transition_workflow(self, transition: CargoWorkflowTransition) -> None:
        """Зафиксировать переход статуса и сделать его текущим."""
        await asyncio.to_thread(self._transition_sync, transition)

    async def workflow_history(self, cargo_id: str) -> Sequence[CargoWorkflowTransition]:
        """История переходов статуса груза (старые → новые)."""
        rows = await asyncio.to_thread(
            self._db.query,
            "SELECT * FROM cargo_workflow_transitions WHERE cargo_id = ? ORDER BY occurred_at ASC",
            (cargo_id,),
        )
        return tuple(self._to_transition(row) for row in rows)

    async def list_by_state(
        self,
        state: CargoWorkflowState,
        *,
        sort_by: str = _DEFAULT_SORT,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Cargo]:
        """Грузы в выбранном статусе."""
        order = _SORT_SQL.get(sort_by, _SORT_SQL[_DEFAULT_SORT])
        rows = await asyncio.to_thread(
            self._db.query,
            f"SELECT * FROM cargos WHERE workflow_state = ? ORDER BY {order} LIMIT ? OFFSET ?",
            (state.value, limit, offset),
        )
        return tuple(self._to_cargo(row) for row in rows)

    async def is_ignored_offer(self, cargo: Cargo) -> bool:
        """Скрыто ли именно это предложение груза (по fingerprint)."""
        rows = await asyncio.to_thread(
            self._db.query,
            "SELECT 1 FROM ignored_offers WHERE cargo_id = ? AND offer_fingerprint = ? LIMIT 1",
            (cargo.id, cargo_offer_fingerprint(cargo)),
        )
        return bool(rows)

    async def count_today(self, source_id: str | None = None) -> int:
        """Сколько грузов сохранено сегодня."""
        start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC).isoformat()
        if source_id is None:
            rows = await asyncio.to_thread(
                self._db.query,
                "SELECT COUNT(*) AS n FROM cargos WHERE created_at >= ?",
                (start,),
            )
        else:
            rows = await asyncio.to_thread(
                self._db.query,
                "SELECT COUNT(*) AS n FROM cargos WHERE source_id = ? AND created_at >= ?",
                (source_id, start),
            )
        return int(rows[0]["n"]) if rows else 0

    # ── Синхронная часть под sqlite lock ──────────────────────────────────────

    def _save_many_sync(self, cargos: tuple[Cargo, ...]) -> None:
        states = self._states_for(tuple(cargo.id for cargo in cargos))
        now = datetime.now(UTC).isoformat()
        cargo_rows = tuple(self._cargo_row(cargo, now, states.get(cargo.id)) for cargo in cargos)
        self._db.executemany(
            """
            INSERT INTO cargos (
                id, source_id, title, url, category, weight_kg, length_cm, width_cm,
                height_cm, volume_m3, pallet_count, required_body_type, loading_region,
                unloading_region, payment_amount, distance_km, created_at, updated_at,
                raw_json, offer_fingerprint, workflow_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_id = excluded.source_id,
                title = excluded.title,
                url = excluded.url,
                category = excluded.category,
                weight_kg = excluded.weight_kg,
                length_cm = excluded.length_cm,
                width_cm = excluded.width_cm,
                height_cm = excluded.height_cm,
                volume_m3 = excluded.volume_m3,
                pallet_count = excluded.pallet_count,
                required_body_type = excluded.required_body_type,
                loading_region = excluded.loading_region,
                unloading_region = excluded.unloading_region,
                payment_amount = excluded.payment_amount,
                distance_km = excluded.distance_km,
                updated_at = excluded.updated_at,
                raw_json = excluded.raw_json,
                offer_fingerprint = excluded.offer_fingerprint
            """,
            cargo_rows,
        )
        self._db.executemany(
            """
            INSERT OR IGNORE INTO cargo_offer_versions (
                id, cargo_id, observed_at, offer_fingerprint, loading_region,
                unloading_region, payment_amount, distance_km, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(self._version_row(cargo, now) for cargo in cargos),
        )
        new_transitions = tuple(
            CargoWorkflowTransition.create(
                cargo_id=cargo.id,
                from_state=None,
                action=CargoWorkflowAction.DISCOVER,
                actor="source",
                trace_id="",
                offer_fingerprint=cargo_offer_fingerprint(cargo),
            )
            for cargo in cargos
            if cargo.id not in states
        )
        self._insert_transitions(new_transitions)

    def _states_for(self, cargo_ids: tuple[str, ...]) -> dict[str, CargoWorkflowState]:
        states: dict[str, CargoWorkflowState] = {}
        for start in range(0, len(cargo_ids), 500):
            chunk = cargo_ids[start : start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            rows = self._db.query(
                f"SELECT id, workflow_state FROM cargos WHERE id IN ({placeholders})",
                tuple(chunk),
            )
            states.update(
                {str(row["id"]): CargoWorkflowState(str(row["workflow_state"])) for row in rows}
            )
        return states

    def _transition_sync(self, transition: CargoWorkflowTransition) -> None:
        current = self._current_fingerprint(transition.cargo_id)
        effective = (
            transition
            if transition.offer_fingerprint
            else CargoWorkflowTransition(
                id=transition.id,
                cargo_id=transition.cargo_id,
                from_state=transition.from_state,
                to_state=transition.to_state,
                action=transition.action,
                occurred_at=transition.occurred_at,
                actor=transition.actor,
                note=transition.note,
                trace_id=transition.trace_id,
                offer_fingerprint=current,
            )
        )
        self._insert_transitions((effective,))
        self._db.execute(
            "UPDATE cargos SET workflow_state = ?, updated_at = ? WHERE id = ?",
            (effective.to_state.value, datetime.now(UTC).isoformat(), effective.cargo_id),
        )
        if effective.to_state is CargoWorkflowState.IGNORED and effective.offer_fingerprint:
            self._db.execute(
                """
                INSERT OR IGNORE INTO ignored_offers (cargo_id, offer_fingerprint, ignored_at)
                VALUES (?, ?, ?)
                """,
                (
                    effective.cargo_id,
                    effective.offer_fingerprint,
                    effective.occurred_at.isoformat(),
                ),
            )

    def _insert_transitions(self, transitions: tuple[CargoWorkflowTransition, ...]) -> None:
        if not transitions:
            return
        self._db.executemany(
            """
            INSERT INTO cargo_workflow_transitions (
                id, cargo_id, from_state, to_state, action, occurred_at, actor, note,
                trace_id, offer_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(self._transition_row(transition) for transition in transitions),
        )

    def _current_fingerprint(self, cargo_id: str) -> str:
        rows = self._db.query("SELECT offer_fingerprint FROM cargos WHERE id = ?", (cargo_id,))
        return str(rows[0]["offer_fingerprint"]) if rows else ""

    @staticmethod
    def _cargo_row(
        cargo: Cargo, updated_at: str, state: CargoWorkflowState | None
    ) -> tuple[object, ...]:
        return (
            cargo.id,
            cargo.source_id,
            cargo.title,
            cargo.url,
            cargo.category.value,
            cargo.weight_kg,
            cargo.length_cm,
            cargo.width_cm,
            cargo.height_cm,
            cargo.volume_m3,
            cargo.pallet_count,
            cargo.required_body_type.value if cargo.required_body_type is not None else None,
            cargo.loading_region,
            cargo.unloading_region,
            str(cargo.payment_amount) if cargo.payment_amount is not None else None,
            cargo.distance_km,
            cargo.created_at.isoformat(),
            updated_at,
            json.dumps(dict(cargo.raw), ensure_ascii=False, default=str),
            cargo_offer_fingerprint(cargo),
            (state or CargoWorkflowState.NEW).value,
        )

    @staticmethod
    def _version_row(cargo: Cargo, observed_at: str) -> tuple[object, ...]:
        return (
            uuid4().hex,
            cargo.id,
            observed_at,
            cargo_offer_fingerprint(cargo),
            cargo.loading_region,
            cargo.unloading_region,
            str(cargo.payment_amount) if cargo.payment_amount is not None else None,
            cargo.distance_km,
            json.dumps(dict(cargo.raw), ensure_ascii=False, default=str),
        )

    @staticmethod
    def _transition_row(transition: CargoWorkflowTransition) -> tuple[object, ...]:
        return (
            transition.id,
            transition.cargo_id,
            transition.from_state.value if transition.from_state is not None else None,
            transition.to_state.value,
            transition.action.value,
            transition.occurred_at.isoformat(),
            transition.actor,
            transition.note,
            transition.trace_id,
            transition.offer_fingerprint,
        )

    @staticmethod
    def _to_cargo(row: Any) -> Cargo:
        payment = row["payment_amount"]
        body_type = row["required_body_type"]
        raw = json.loads(str(row["raw_json"])) if row["raw_json"] else {}
        return Cargo(
            id=str(row["id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            category=CargoCategory(str(row["category"])),
            weight_kg=int(row["weight_kg"]) if row["weight_kg"] is not None else None,
            length_cm=int(row["length_cm"]) if row["length_cm"] is not None else None,
            width_cm=int(row["width_cm"]) if row["width_cm"] is not None else None,
            height_cm=int(row["height_cm"]) if row["height_cm"] is not None else None,
            volume_m3=float(row["volume_m3"]) if row["volume_m3"] is not None else None,
            pallet_count=int(row["pallet_count"]) if row["pallet_count"] is not None else None,
            required_body_type=BodyType(str(body_type)) if body_type is not None else None,
            loading_region=str(row["loading_region"]),
            unloading_region=str(row["unloading_region"]),
            payment_amount=Decimal(str(payment)) if payment is not None else None,
            distance_km=float(row["distance_km"]) if row["distance_km"] is not None else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            raw=raw if isinstance(raw, dict) else {},
        )

    @staticmethod
    def _to_transition(row: Any) -> CargoWorkflowTransition:
        from_state = row["from_state"]
        return CargoWorkflowTransition(
            id=str(row["id"]),
            cargo_id=str(row["cargo_id"]),
            from_state=CargoWorkflowState(str(from_state)) if from_state is not None else None,
            to_state=CargoWorkflowState(str(row["to_state"])),
            action=CargoWorkflowAction(str(row["action"])),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            actor=str(row["actor"]),
            note=str(row["note"]),
            trace_id=str(row["trace_id"]),
            offer_fingerprint=str(row["offer_fingerprint"]),
        )
