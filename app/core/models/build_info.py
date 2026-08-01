"""Информация о сборке приложения: версия, дата, git-коммит, режим.

Чистая доменная модель. Чтение VERSION/окружения выполняет провайдер
в ``app.infrastructure.system.build_info`` — ядро файлов не читает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class BuildMode(Enum):
    """Режим сборки приложения."""

    DEBUG = "debug"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class BuildInfo:
    """Метаданные сборки. Показываются в окне «О программе» и логах.

    ``build_date`` и ``git_commit`` заполняются на этапе упаковки (.app);
    в dev-режиме допустимы ``None``.
    """

    version: str
    build_date: datetime | None
    git_commit: str | None
    mode: BuildMode

    @property
    def is_debug(self) -> bool:
        """Истина для отладочной сборки."""
        return self.mode is BuildMode.DEBUG

    def display(self) -> str:
        """Короткая строка для UI, например: «0.1.0-alpha · debug»."""
        return f"{self.version} · {self.mode.value}"
