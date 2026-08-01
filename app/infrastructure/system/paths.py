"""Платформозависимые пути приложения (реализация порта PathProvider).

macOS: настройки/данные — ~/Library/Application Support/LogistAI,
логи — ~/Library/Logs/LogistAI. Windows/Linux — соответствующие каталоги
platformdirs, без изменений кода (ADR-0001: замена только адаптеров).
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "LogistAI"


class PlatformPaths:
    """PathProvider на platformdirs."""

    def __init__(self, app_name: str = _APP_NAME) -> None:
        self._dirs = PlatformDirs(appname=app_name, appauthor=False)

    @property
    def config_dir(self) -> Path:
        """Каталог настроек (settings.json)."""
        return Path(self._dirs.user_data_dir)

    @property
    def data_dir(self) -> Path:
        """Каталог данных (БД журнала и т.п.)."""
        return Path(self._dirs.user_data_dir)

    @property
    def logs_dir(self) -> Path:
        """Каталог логов (app.log с ротацией)."""
        return Path(self._dirs.user_log_dir)

    @property
    def plugins_dir(self) -> Path:
        """Каталог пользовательских плагинов."""
        return self.data_dir / "plugins"
