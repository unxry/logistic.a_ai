"""Scheduler Runtime — двигатель фоновых задач платформы.

Позже именно он запускает ATI Monitor, Cargo Search, плагины, чистку,
health-check, аналитику и бэкапы — без изменения архитектуры.
"""

from app.services.scheduler.handlers import (
    PauseJobHandler,
    ResumeJobHandler,
    RunJobNowHandler,
    StartSchedulerHandler,
    StopSchedulerHandler,
)
from app.services.scheduler.jobs import HistoryCleanupJob
from app.services.scheduler.registry import JobRegistry
from app.services.scheduler.runtime import SchedulerRuntime

__all__ = [
    "HistoryCleanupJob",
    "JobRegistry",
    "PauseJobHandler",
    "ResumeJobHandler",
    "RunJobNowHandler",
    "SchedulerRuntime",
    "StartSchedulerHandler",
    "StopSchedulerHandler",
]
