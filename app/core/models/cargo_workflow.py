"""Жизненный цикл груза в рабочем месте диспетчера.

Статус груза — только enum, без ``bool``-флагов. Каждый переход фиксируется
отдельной записью истории и доменным событием, чтобы аналитика и UI видели
одну и ту же правду.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.core.clock import utc_now


class CargoWorkflowState(Enum):
    """Статусы груза в производственном workflow диспетчера."""

    NEW = "new"
    FAVORITE = "favorite"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    IGNORED = "ignored"


class CargoWorkflowAction(Enum):
    """Действие, которое переводит груз между статусами."""

    DISCOVER = "discover"
    FAVORITE = "favorite"
    ASSIGN = "assign"
    START = "start"
    COMPLETE = "complete"
    REJECT = "reject"
    IGNORE = "ignore"


_ACTION_TARGETS: dict[CargoWorkflowAction, CargoWorkflowState] = {
    CargoWorkflowAction.DISCOVER: CargoWorkflowState.NEW,
    CargoWorkflowAction.FAVORITE: CargoWorkflowState.FAVORITE,
    CargoWorkflowAction.ASSIGN: CargoWorkflowState.ASSIGNED,
    CargoWorkflowAction.START: CargoWorkflowState.IN_PROGRESS,
    CargoWorkflowAction.COMPLETE: CargoWorkflowState.COMPLETED,
    CargoWorkflowAction.REJECT: CargoWorkflowState.REJECTED,
    CargoWorkflowAction.IGNORE: CargoWorkflowState.IGNORED,
}


@dataclass(frozen=True, slots=True)
class CargoWorkflowTransition:
    """Один переход статуса груза."""

    id: str
    cargo_id: str
    from_state: CargoWorkflowState | None
    to_state: CargoWorkflowState
    action: CargoWorkflowAction
    occurred_at: datetime = field(default_factory=utc_now)
    actor: str = "system"
    note: str = ""
    trace_id: str = ""
    offer_fingerprint: str = ""

    @classmethod
    def create(
        cls,
        *,
        cargo_id: str,
        from_state: CargoWorkflowState | None,
        action: CargoWorkflowAction,
        actor: str = "system",
        note: str = "",
        trace_id: str = "",
        offer_fingerprint: str = "",
    ) -> CargoWorkflowTransition:
        """Создать переход к состоянию, соответствующему действию."""
        return cls(
            id=uuid4().hex,
            cargo_id=cargo_id,
            from_state=from_state,
            to_state=_ACTION_TARGETS[action],
            action=action,
            actor=actor,
            note=note,
            trace_id=trace_id,
            offer_fingerprint=offer_fingerprint,
        )
