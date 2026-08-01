"""Команды (frozen dataclasses) для CommandBus — публичный каталог."""

from app.core.commands.base import Command
from app.core.commands.cargo import FavoriteCargo, IgnoreCargo, TransitionCargoWorkflow
from app.core.commands.notifications import SendNotification
from app.core.commands.scheduler import (
    PauseJob,
    ResumeJob,
    RunJobNow,
    StartScheduler,
    StopScheduler,
)
from app.core.commands.settings import SaveSettings
from app.core.commands.telegram import SendTestMessage, VerifyTelegram

__all__ = [
    "Command",
    "FavoriteCargo",
    "IgnoreCargo",
    "PauseJob",
    "ResumeJob",
    "RunJobNow",
    "SaveSettings",
    "SendNotification",
    "SendTestMessage",
    "StartScheduler",
    "StopScheduler",
    "TransitionCargoWorkflow",
    "VerifyTelegram",
]
