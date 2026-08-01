"""Команды рабочего жизненного цикла груза."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.commands.base import Command
from app.core.models.cargo_workflow import CargoWorkflowAction, CargoWorkflowTransition


@dataclass(frozen=True, slots=True)
class TransitionCargoWorkflow(Command[CargoWorkflowTransition]):
    """Перевести груз в новый workflow-статус через CommandBus."""

    cargo_id: str
    action: CargoWorkflowAction
    actor: str = "dispatcher"
    note: str = ""
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class FavoriteCargo(Command[CargoWorkflowTransition]):
    """Сохранить груз в избранном."""

    cargo_id: str
    actor: str = "dispatcher"
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class IgnoreCargo(Command[CargoWorkflowTransition]):
    """Больше не показывать текущее предложение груза."""

    cargo_id: str
    actor: str = "dispatcher"
    trace_id: str = ""
