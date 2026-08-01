"""События Search Engine (с trace_id для сквозной корреляции)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event


@dataclass(frozen=True, slots=True)
class CargoMatched(Event):
    """Груз совместим с профилем (кандидат к перевозке)."""

    cargo_id: str
    vehicle_profile_id: str
    score: int
    trace_id: str


@dataclass(frozen=True, slots=True)
class CargoRejected(Event):
    """Груз отклонён проверкой совместимости."""

    cargo_id: str
    vehicle_profile_id: str
    reasons: tuple[str, ...]
    trace_id: str


@dataclass(frozen=True, slots=True)
class SearchCompleted(Event):
    """Поиск завершён."""

    query_id: str
    trace_id: str
    total_candidates: int
    matched: int
