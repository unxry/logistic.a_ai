"""События интеллектуального подбора."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.matching import MatchingDecision


@dataclass(frozen=True, slots=True)
class BestCargoSelected(Event):
    """Выбран лучший груз для водителя."""

    cargo_id: str
    driver_id: str
    final_score: int
    trace_id: str


@dataclass(frozen=True, slots=True)
class CargoRejectedByPreference(Event):
    """Груз отклонён предпочтениями водителя (не совместимостью)."""

    cargo_id: str
    driver_id: str
    reason: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class MatchingDecisionCreated(Event):
    """Зафиксировано решение подбора (сырьё для будущего обучения)."""

    decision: MatchingDecision
