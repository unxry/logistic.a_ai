"""Сервис workflow груза: команды → repository/history/events."""

from __future__ import annotations

from app.core.commands import FavoriteCargo, IgnoreCargo, TransitionCargoWorkflow
from app.core.events import (
    CargoAssigned,
    CargoCompleted,
    CargoFavorited,
    CargoIgnored,
    CargoRejectedByDispatcher,
    CargoWorkflowTransitioned,
    CargoWorkStarted,
)
from app.core.models.cargo_workflow import (
    CargoWorkflowAction,
    CargoWorkflowState,
    CargoWorkflowTransition,
)
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.severity import Severity
from app.core.ports import CargoRepository, EventPublisher, HistoryRepository

_EVENT_BY_STATE: dict[CargoWorkflowState, type[CargoWorkflowTransitioned]] = {
    CargoWorkflowState.FAVORITE: CargoFavorited,
    CargoWorkflowState.ASSIGNED: CargoAssigned,
    CargoWorkflowState.IN_PROGRESS: CargoWorkStarted,
    CargoWorkflowState.COMPLETED: CargoCompleted,
    CargoWorkflowState.REJECTED: CargoRejectedByDispatcher,
    CargoWorkflowState.IGNORED: CargoIgnored,
}

_TITLE_BY_ACTION: dict[CargoWorkflowAction, str] = {
    CargoWorkflowAction.DISCOVER: "Груз найден",
    CargoWorkflowAction.FAVORITE: "Груз добавлен в избранное",
    CargoWorkflowAction.ASSIGN: "Груз передан перевозчику",
    CargoWorkflowAction.START: "Груз взят в работу",
    CargoWorkflowAction.COMPLETE: "Груз завершён",
    CargoWorkflowAction.REJECT: "Отказ от груза",
    CargoWorkflowAction.IGNORE: "Груз игнорируется",
}


class CargoWorkflowService:
    """Единая точка смены статуса груза."""

    def __init__(
        self,
        *,
        repository: CargoRepository,
        history: HistoryRepository,
        events: EventPublisher,
    ) -> None:
        self._repository = repository
        self._history = history
        self._events = events

    async def transition(
        self,
        cargo_id: str,
        action: CargoWorkflowAction,
        *,
        actor: str = "dispatcher",
        note: str = "",
        trace_id: str = "",
    ) -> CargoWorkflowTransition:
        """Перевести груз по action, записать историю и опубликовать событие."""
        from_state = await self._repository.workflow_state(cargo_id)
        transition = CargoWorkflowTransition.create(
            cargo_id=cargo_id,
            from_state=from_state,
            action=action,
            actor=actor,
            note=note,
            trace_id=trace_id,
        )
        await self._repository.transition_workflow(transition)
        await self._history.add(
            HistoryEntry.create(
                kind=HistoryKind.USER_ACTION,
                severity=Severity.SUCCESS,
                title=_TITLE_BY_ACTION[action],
                details=note,
                source=actor,
                trace_id=trace_id,
            )
        )
        event_type = _EVENT_BY_STATE.get(transition.to_state, CargoWorkflowTransitioned)
        self._events.publish(event_type(transition=transition))
        return transition


class TransitionCargoWorkflowHandler:
    """TransitionCargoWorkflow → CargoWorkflowService."""

    def __init__(self, service: CargoWorkflowService) -> None:
        self._service = service

    async def __call__(self, command: TransitionCargoWorkflow) -> CargoWorkflowTransition:
        """Выполнить переход статуса."""
        return await self._service.transition(
            command.cargo_id,
            command.action,
            actor=command.actor,
            note=command.note,
            trace_id=command.trace_id,
        )


class FavoriteCargoHandler:
    """FavoriteCargo → CargoWorkflowAction.FAVORITE."""

    def __init__(self, service: CargoWorkflowService) -> None:
        self._service = service

    async def __call__(self, command: FavoriteCargo) -> CargoWorkflowTransition:
        """Добавить груз в избранное."""
        return await self._service.transition(
            command.cargo_id,
            CargoWorkflowAction.FAVORITE,
            actor=command.actor,
            trace_id=command.trace_id,
        )


class IgnoreCargoHandler:
    """IgnoreCargo → CargoWorkflowAction.IGNORE."""

    def __init__(self, service: CargoWorkflowService) -> None:
        self._service = service

    async def __call__(self, command: IgnoreCargo) -> CargoWorkflowTransition:
        """Скрыть текущее предложение груза."""
        return await self._service.transition(
            command.cargo_id,
            CargoWorkflowAction.IGNORE,
            actor=command.actor,
            trace_id=command.trace_id,
        )
