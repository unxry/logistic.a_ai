"""ViewModel главного окна (MVVM).

Цепочка строго ``View → ViewModel → Service``: окно не знает ни о сервисах,
ни о контейнере — только о своих ViewModel'ях (MainViewModel + Dashboard).
"""

from __future__ import annotations

from app.core.models.build_info import BuildInfo


class MainViewModel:
    """Презентационное состояние главного окна."""

    def __init__(self, build_info: BuildInfo) -> None:
        self._build_info = build_info

    @property
    def window_title(self) -> str:
        """Заголовок окна."""
        return "LogistAI"

    @property
    def status_line(self) -> str:
        """Строка версии для сайдбара и статус-бара."""
        return f"LogistAI {self._build_info.display()}"
