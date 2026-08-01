"""Единая шкала важности для уведомлений и записей журнала."""

from __future__ import annotations

from enum import Enum


class Severity(Enum):
    """Важность события/уведомления."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"
