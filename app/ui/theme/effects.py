"""Safe wrappers around Qt graphics effects.

PySide wrappers can outlive their underlying C++ QObject. Directly calling
``shadow.blurRadius()`` after Qt has replaced/deleted the graphics effect raises
``RuntimeError: Internal C++ object ... already deleted``. These wrappers are
the only place where shadow properties are read/written.
"""

from __future__ import annotations

import weakref

import shiboken6
from PySide6.QtCore import QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from app.ui.theme import tokens as t
from app.ui.theme.animation_manager import AnimationManager


class SafeGraphicsEffect:
    """Thin validity guard for a Qt graphics effect wrapper."""

    def __init__(self, effect: QGraphicsDropShadowEffect | None = None) -> None:
        self._effect = effect

    @property
    def is_valid(self) -> bool:
        """Whether the Python wrapper still points to a live C++ QObject."""
        return self._effect is not None and shiboken6.isValid(self._effect)

    @property
    def effect(self) -> QGraphicsDropShadowEffect | None:
        """Return the effect only while it is valid."""
        return self._effect if self.is_valid else None


class SafeShadow(SafeGraphicsEffect):
    """Safe owner-aware drop shadow used by premium cards."""

    def __init__(self, widget: QWidget, spec: t.ShadowSpec) -> None:
        super().__init__(None)
        self._widget_ref = weakref.ref(widget)
        self._last_spec = spec
        self._install(spec)

    @property
    def widget(self) -> QWidget | None:
        """Return owner widget while Qt still considers it alive."""
        widget = self._widget_ref()
        return widget if widget is not None and shiboken6.isValid(widget) else None

    def ensure(self) -> QGraphicsDropShadowEffect | None:
        """Return a live effect, reinstalling it when Qt deleted/replaced it."""
        widget = self.widget
        if widget is None:
            return None
        current = self.effect
        if current is None or widget.graphicsEffect() is not current:
            return self._install(self._last_spec)
        return current

    def animate(
        self,
        target: t.ShadowSpec,
        duration_ms: int = t.DURATION_BASE,
    ) -> QVariantAnimation | None:
        """Animate to target through AnimationManager."""
        return AnimationManager.instance().animate_shadow(self, target, duration_ms)

    def blur_radius(self) -> float | None:
        """Safe ``blurRadius()``."""
        effect = self.ensure()
        return float(effect.blurRadius()) if effect is not None else None

    def set_blur_radius(self, value: float) -> None:
        """Safe ``setBlurRadius()``."""
        effect = self.ensure()
        if effect is not None:
            effect.setBlurRadius(value)

    def color(self) -> QColor | None:
        """Safe ``color()``."""
        effect = self.ensure()
        return effect.color() if effect is not None else None

    def set_color(self, color: QColor) -> None:
        """Safe ``setColor()``."""
        effect = self.ensure()
        if effect is not None:
            effect.setColor(color)

    def y_offset(self) -> float | None:
        """Safe y-offset read."""
        effect = self.ensure()
        return float(effect.yOffset()) if effect is not None else None

    def set_offset(self, x: float, y: float) -> None:
        """Safe ``setOffset()``."""
        effect = self.ensure()
        if effect is not None:
            effect.setOffset(x, y)

    def apply(self, spec: t.ShadowSpec) -> None:
        """Apply a shadow spec immediately."""
        self._last_spec = spec
        effect = self.ensure()
        if effect is None:
            return
        effect.setBlurRadius(spec.blur)
        effect.setOffset(0, spec.y_offset)
        effect.setColor(QColor(*spec.rgba))

    def _install(self, spec: t.ShadowSpec) -> QGraphicsDropShadowEffect | None:
        widget = self.widget
        if widget is None:
            return None
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(spec.blur)
        effect.setOffset(0, spec.y_offset)
        effect.setColor(QColor(*spec.rgba))
        widget.setGraphicsEffect(effect)
        self._effect = effect
        self._last_spec = spec
        return effect
