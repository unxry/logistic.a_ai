"""События workflow груза: каждый переход публикуется в EventBus."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.cargo_workflow import CargoWorkflowTransition


@dataclass(frozen=True, slots=True)
class CargoWorkflowTransitioned(Event):
    """Базовое событие перехода статуса."""

    transition: CargoWorkflowTransition


@dataclass(frozen=True, slots=True)
class CargoFavorited(CargoWorkflowTransitioned):
    """Груз добавлен в избранное."""


@dataclass(frozen=True, slots=True)
class CargoAssigned(CargoWorkflowTransitioned):
    """Груз передан перевозчику."""


@dataclass(frozen=True, slots=True)
class CargoWorkStarted(CargoWorkflowTransitioned):
    """Груз взят в работу."""


@dataclass(frozen=True, slots=True)
class CargoCompleted(CargoWorkflowTransitioned):
    """Груз завершён."""


@dataclass(frozen=True, slots=True)
class CargoRejectedByDispatcher(CargoWorkflowTransitioned):
    """Диспетчер отказался от груза."""


@dataclass(frozen=True, slots=True)
class CargoIgnored(CargoWorkflowTransitioned):
    """Груз скрыт из рекомендаций."""
