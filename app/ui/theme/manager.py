"""Live Light/Dark/System theme manager."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget

from app.core.models.settings import Theme
from app.ui.theme import tokens
from app.ui.theme.fonts import resolve_font_stack
from app.ui.theme.qss import build_global_qss


@runtime_checkable
class _ThemeRefreshable(Protocol):
    def refresh_theme(self) -> None: ...


class ThemeObserver:
    """Tiny observer wrapper used by tests and future UI components."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback


class ThemeTransitionOverlay(QWidget):
    """Simple fade overlay to hide QSS/token switching flashes."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()
        self._alpha = 0.0
        self._animation: QVariantAnimation | None = None

    def run(self, apply: Callable[[], None]) -> None:
        """Fade out, apply theme, fade in."""
        parent = self.parentWidget()
        self.setGeometry(parent.rect() if parent is not None else self.rect())
        self.show()
        self.raise_()
        self._animate(0.0, 1.0, 140, lambda: self._apply_then_fade(apply))

    def _apply_then_fade(self, apply: Callable[[], None]) -> None:
        apply()
        self._animate(1.0, 0.0, 200, self.hide)

    def _animate(
        self,
        start: float,
        end: float,
        duration_ms: int,
        finished: Callable[[], None],
    ) -> None:
        if self._animation is not None:
            self._animation.stop()
        animation = QVariantAnimation(self)
        animation.setDuration(duration_ms)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)

        def _tick(value: object) -> None:
            self._alpha = float(value) if isinstance(value, int | float) else 0.0
            self.setStyleSheet(
                f"QWidget {{ background: rgba(0, 0, 0, {self._alpha * 0.08:.3f}); }}"
            )

        animation.valueChanged.connect(_tick)
        animation.finished.connect(finished)
        self._animation = animation
        animation.start()


class ThemeManager:
    """Apply Light/Dark/System themes without recreating MainWindow."""

    def __init__(self, app: QApplication, root: QWidget) -> None:
        self._app = app
        self._root = root
        self._observers: list[ThemeObserver] = []
        self._overlay = ThemeTransitionOverlay(root)

    def add_observer(self, observer: ThemeObserver) -> None:
        self._observers.append(observer)

    def apply(self, theme: Theme, *, animated: bool = True) -> str:
        """Apply theme and return concrete token theme: ``light`` or ``dark``."""
        concrete = self.resolve(theme)

        def _apply() -> None:
            tokens.FONT_STACK = resolve_font_stack()
            tokens.apply_theme(concrete)
            self._app.setStyleSheet(build_global_qss())
            self._root.setStyleSheet(build_global_qss())
            self._refresh_tree(self._root)
            for observer in tuple(self._observers):
                observer.callback(concrete)

        if animated and self._root.isVisible():
            self._overlay.run(_apply)
        else:
            _apply()
        return concrete

    def resolve(self, theme: Theme) -> str:
        if theme is Theme.LIGHT:
            return "light"
        if theme is Theme.DARK:
            return "dark"
        return self._system_theme()

    def _system_theme(self) -> str:
        hints = self._app.styleHints()
        color_scheme = getattr(hints, "colorScheme", lambda: None)()
        if color_scheme is not None and str(color_scheme).lower().endswith("dark"):
            return "dark"
        bg = self._app.palette().color(QPalette.ColorRole.Window)
        return "dark" if bg.lightness() < 128 else "light"

    def _refresh_tree(self, widget: QWidget) -> None:
        if isinstance(widget, _ThemeRefreshable):
            widget.refresh_theme()
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
        for child in widget.findChildren(QWidget):
            if isinstance(child, _ThemeRefreshable):
                child.refresh_theme()
            child_style = child.style()
            child_style.unpolish(child)
            child_style.polish(child)
            child.update()
