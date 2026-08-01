"""Порт путей операционной системы."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PathProvider(Protocol):
    """Платформозависимые каталоги приложения (реализация: platformdirs)."""

    @property
    def config_dir(self) -> Path:
        """Каталог настроек (macOS: ~/Library/Application Support/LogistAI)."""
        ...

    @property
    def data_dir(self) -> Path:
        """Каталог данных (БД журнала и т.п.)."""
        ...

    @property
    def logs_dir(self) -> Path:
        """Каталог логов (macOS: ~/Library/Logs/LogistAI)."""
        ...

    @property
    def plugins_dir(self) -> Path:
        """Каталог пользовательских плагинов."""
        ...
