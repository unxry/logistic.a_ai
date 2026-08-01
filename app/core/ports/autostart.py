"""Порт автозапуска приложения при входе в систему."""

from __future__ import annotations

from typing import Protocol


class AutostartManager(Protocol):
    """Автозапуск (macOS: LaunchAgent plist; Windows: ключ реестра Run)."""

    def is_enabled(self) -> bool:
        """Включён ли автозапуск сейчас."""
        ...

    def enable(self) -> None:
        """Включить автозапуск."""
        ...

    def disable(self) -> None:
        """Выключить автозапуск."""
        ...
