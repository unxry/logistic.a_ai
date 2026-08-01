"""Доменные модели (dataclasses, enums)."""

from app.core.models.cargo_identity import cargo_offer_fingerprint
from app.core.models.cargo_workflow import (
    CargoWorkflowAction,
    CargoWorkflowState,
    CargoWorkflowTransition,
)
from app.core.models.notification_history import NotificationHistoryEntry, NotificationOpenState

__all__ = [
    "CargoWorkflowAction",
    "CargoWorkflowState",
    "CargoWorkflowTransition",
    "NotificationHistoryEntry",
    "NotificationOpenState",
    "cargo_offer_fingerprint",
]
