"""Доменные события (frozen dataclasses) для EventBus — публичный каталог."""

from app.core.events.app import AppClosing, AppStarted, ErrorOccurred, LogRecordAdded
from app.core.events.base import Event
from app.core.events.matching import (
    BestCargoSelected,
    CargoRejectedByPreference,
    MatchingDecisionCreated,
)
from app.core.events.notifications import (
    NotificationDelivered,
    NotificationFailed,
    NotificationQueued,
    NotificationSending,
)
from app.core.events.routes import ProfitCalculated, RouteCalculated
from app.core.events.scheduler import (
    JobCompleted,
    JobFailed,
    JobSkipped,
    JobStarted,
    SchedulerStarted,
    SchedulerStopped,
)
from app.core.events.search import CargoMatched, CargoRejected, SearchCompleted
from app.core.events.settings import SettingsChanged
from app.core.events.sources import (
    CargoReceived,
    CargoUpdated,
    SourceCompleted,
    SourceFailed,
    SourceHealthChanged,
    SourceRegistered,
    SourceStarted,
)
from app.core.events.telegram import TelegramStatusChanged
from app.core.events.workflow import (
    CargoAssigned,
    CargoCompleted,
    CargoFavorited,
    CargoIgnored,
    CargoRejectedByDispatcher,
    CargoWorkflowTransitioned,
    CargoWorkStarted,
)

__all__ = [
    "AppClosing",
    "AppStarted",
    "BestCargoSelected",
    "CargoAssigned",
    "CargoCompleted",
    "CargoFavorited",
    "CargoIgnored",
    "CargoMatched",
    "CargoReceived",
    "CargoRejected",
    "CargoRejectedByDispatcher",
    "CargoRejectedByPreference",
    "CargoUpdated",
    "CargoWorkStarted",
    "CargoWorkflowTransitioned",
    "ErrorOccurred",
    "Event",
    "JobCompleted",
    "JobFailed",
    "JobSkipped",
    "JobStarted",
    "LogRecordAdded",
    "MatchingDecisionCreated",
    "NotificationDelivered",
    "NotificationFailed",
    "NotificationQueued",
    "NotificationSending",
    "ProfitCalculated",
    "RouteCalculated",
    "SchedulerStarted",
    "SchedulerStopped",
    "SearchCompleted",
    "SettingsChanged",
    "SourceCompleted",
    "SourceFailed",
    "SourceHealthChanged",
    "SourceRegistered",
    "SourceStarted",
    "TelegramStatusChanged",
]
