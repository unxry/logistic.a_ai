"""Состояние подключения к внешнему сервису (Telegram, будущие источники)."""

from __future__ import annotations

from enum import Enum


class ConnectionState(Enum):
    """Машина состояний подключения."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
