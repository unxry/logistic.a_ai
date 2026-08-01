"""SQLite-база приложения: подключение, WAL, миграции схемы.

Синхронный слой (sqlite3); репозитории оборачивают вызовы в
``asyncio.to_thread``, чтобы не блокировать петлю (ADR-0007).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from app.core.errors import StorageError

logger = logging.getLogger(__name__)

# Миграции схемы: (версия, DDL). PRAGMA user_version хранит текущую версию.
_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE history (
            id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            trace_id TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX idx_history_occurred ON history(occurred_at DESC);
        CREATE INDEX idx_history_kind ON history(kind);
        CREATE INDEX idx_history_trace ON history(trace_id);
        """,
    ),
    (
        2,
        """
        CREATE TABLE matching_decisions (
            id TEXT PRIMARY KEY,
            cargo_id TEXT NOT NULL,
            vehicle_profile_id TEXT NOT NULL DEFAULT '',
            driver_id TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL,
            profit TEXT,
            explanation TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            selected INTEGER NOT NULL,
            rejected_reason TEXT NOT NULL DEFAULT '',
            trace_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_decisions_driver ON matching_decisions(driver_id);
        CREATE INDEX idx_decisions_created ON matching_decisions(created_at DESC);
        """,
    ),
    (
        3,
        """
        ALTER TABLE matching_decisions ADD COLUMN distance_km REAL;
        """,
    ),
    (
        4,
        """
        CREATE TABLE cargos (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            weight_kg INTEGER,
            length_cm INTEGER,
            width_cm INTEGER,
            height_cm INTEGER,
            volume_m3 REAL,
            pallet_count INTEGER,
            required_body_type TEXT,
            loading_region TEXT NOT NULL DEFAULT '',
            unloading_region TEXT NOT NULL DEFAULT '',
            payment_amount TEXT,
            distance_km REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            offer_fingerprint TEXT NOT NULL,
            workflow_state TEXT NOT NULL DEFAULT 'new'
        );
        CREATE INDEX idx_cargos_source_created ON cargos(source_id, created_at DESC);
        CREATE INDEX idx_cargos_workflow ON cargos(workflow_state, created_at DESC);
        CREATE INDEX idx_cargos_route ON cargos(loading_region, unloading_region);
        CREATE INDEX idx_cargos_offer_fingerprint ON cargos(offer_fingerprint);

        CREATE TABLE cargo_offer_versions (
            id TEXT PRIMARY KEY,
            cargo_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            offer_fingerprint TEXT NOT NULL,
            loading_region TEXT NOT NULL DEFAULT '',
            unloading_region TEXT NOT NULL DEFAULT '',
            payment_amount TEXT,
            distance_km REAL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(cargo_id) REFERENCES cargos(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_offer_versions_cargo ON cargo_offer_versions(cargo_id, observed_at DESC);
        CREATE UNIQUE INDEX idx_offer_versions_unique
            ON cargo_offer_versions(cargo_id, offer_fingerprint);

        CREATE TABLE cargo_workflow_transitions (
            id TEXT PRIMARY KEY,
            cargo_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            action TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            note TEXT NOT NULL DEFAULT '',
            trace_id TEXT NOT NULL DEFAULT '',
            offer_fingerprint TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(cargo_id) REFERENCES cargos(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_workflow_cargo_time ON cargo_workflow_transitions(cargo_id, occurred_at);
        CREATE INDEX idx_workflow_state_time
            ON cargo_workflow_transitions(to_state, occurred_at DESC);

        CREATE TABLE ignored_offers (
            cargo_id TEXT NOT NULL,
            offer_fingerprint TEXT NOT NULL,
            ignored_at TEXT NOT NULL,
            PRIMARY KEY(cargo_id, offer_fingerprint),
            FOREIGN KEY(cargo_id) REFERENCES cargos(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_ignored_fingerprint ON ignored_offers(offer_fingerprint);

        CREATE TABLE notification_history (
            id TEXT PRIMARY KEY,
            notification_id TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            profit TEXT,
            ai_score INTEGER,
            open_state TEXT NOT NULL DEFAULT 'unopened',
            cargo_id TEXT NOT NULL DEFAULT '',
            trace_id TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX idx_notification_history_time ON notification_history(occurred_at DESC);
        CREATE INDEX idx_notification_history_cargo ON notification_history(cargo_id);
        CREATE INDEX idx_notification_history_trace ON notification_history(trace_id);
        """,
    ),
    (
        5,
        """
        CREATE TABLE route_cache (
            cache_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            estimate_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX idx_route_cache_expires ON route_cache(expires_at);
        CREATE INDEX idx_route_cache_provider ON route_cache(provider);

        CREATE TABLE geocoding_cache (
            location_key TEXT PRIMARY KEY,
            latitude TEXT NOT NULL,
            longitude TEXT NOT NULL,
            normalized_name TEXT NOT NULL DEFAULT '',
            confidence INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX idx_geocoding_cache_expires ON geocoding_cache(expires_at);
        """,
    ),
)


class Database:
    """Обёртка над sqlite3: одно соединение, lock, миграции."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Открыть соединение, включить WAL, применить миграции."""
        if self._conn is not None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
            self._migrate()
        except sqlite3.Error as exc:
            raise StorageError(f"Не удалось открыть базу данных: {exc}") from exc

    def close(self) -> None:
        """Закрыть соединение."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> int:
        """Выполнить запись; вернуть число затронутых строк."""
        conn = self._require_connection()
        try:
            with self._lock:
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageError(f"Ошибка записи в базу: {exc}") from exc

    def executemany(self, sql: str, params: tuple[tuple[object, ...], ...]) -> int:
        """Выполнить пакетную запись в одной транзакции."""
        conn = self._require_connection()
        try:
            with self._lock:
                cursor = conn.executemany(sql, params)
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageError(f"Ошибка пакетной записи в базу: {exc}") from exc

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        """Выполнить чтение; вернуть строки."""
        conn = self._require_connection()
        try:
            with self._lock:
                return list(conn.execute(sql, params).fetchall())
        except sqlite3.Error as exc:
            raise StorageError(f"Ошибка чтения из базы: {exc}") from exc

    def _require_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("База данных не открыта (connect() не вызван)")
        return self._conn

    def _migrate(self) -> None:
        conn = self._require_connection()
        with self._lock:
            row = conn.execute("PRAGMA user_version").fetchone()
            current = int(row[0]) if row is not None else 0
            for version, ddl in _MIGRATIONS:
                if version <= current:
                    continue
                logger.info("SQLite: миграция схемы до версии %d", version)
                conn.executescript(ddl)
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
