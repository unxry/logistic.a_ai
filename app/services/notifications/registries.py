"""Реестры Notification Center: каналы и форматтеры.

Каждый канал/форматтер регистрируется один раз (bootstrap или плагин).
NotificationService и Dispatcher ничего не знают о конкретных реализациях.
"""

from __future__ import annotations

from app.core.errors import NotificationError
from app.core.ports import NotificationChannel, NotificationFormatter


class ChannelRegistry:
    """Реестр каналов доставки (telegram, macos, email, discord, webhook…)."""

    def __init__(self) -> None:
        self._channels: dict[str, NotificationChannel] = {}

    def register(self, channel: NotificationChannel) -> None:
        """Зарегистрировать канал; повторный id — ошибка (признак бага)."""
        if channel.channel_id in self._channels:
            raise NotificationError(f"Канал «{channel.channel_id}» уже зарегистрирован")
        self._channels[channel.channel_id] = channel

    def get(self, channel_id: str) -> NotificationChannel | None:
        """Канал по id; ``None`` — не зарегистрирован."""
        return self._channels.get(channel_id)

    def ids(self) -> tuple[str, ...]:
        """Идентификаторы всех зарегистрированных каналов."""
        return tuple(self._channels)


class FormatterRegistry:
    """Реестр форматтеров по каналам с фолбэком по умолчанию (plain text)."""

    def __init__(self, default: NotificationFormatter) -> None:
        self._default = default
        self._formatters: dict[str, NotificationFormatter] = {}

    def register(self, channel_id: str, formatter: NotificationFormatter) -> None:
        """Назначить каналу собственный форматтер."""
        self._formatters[channel_id] = formatter

    def get(self, channel_id: str) -> NotificationFormatter:
        """Форматтер канала; если не назначен — форматтер по умолчанию."""
        return self._formatters.get(channel_id, self._default)
