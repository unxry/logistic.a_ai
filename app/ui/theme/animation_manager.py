"""Centralized UI animation ownership.

Qt may delete C++ objects while Python wrappers still exist. The manager keeps
only weak owners, stops previous animations per slot, and cleans references when
animations finish so hover/motion code does not accumulate orphan QObjects.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import Final, Protocol

import shiboken6
from PySide6.QtCore import QEasingCurve, QRect, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from app.ui.theme import tokens as t

_SHADOW_SLOT: Final = "shadow"
_OPACITY_SLOT: Final = "opacity"
_GEOMETRY_SLOT: Final = "geometry"
_SCALE_SLOT: Final = "scale"


class _SafeShadowLike(Protocol):
    @property
    def widget(self) -> QWidget | None: ...

    def blur_radius(self) -> float | None: ...

    def y_offset(self) -> float | None: ...

    def color(self) -> QColor | None: ...

    def set_blur_radius(self, value: float) -> None: ...

    def set_offset(self, x: float, y: float) -> None: ...

    def set_color(self, color: QColor) -> None: ...


class AnimationManager:
    """Own, replace, and clean UI animations by weak widget/effect owner."""

    def __init__(self) -> None:
        self._animations: weakref.WeakKeyDictionary[object, dict[str, QVariantAnimation]] = (
            weakref.WeakKeyDictionary()
        )

    @classmethod
    def instance(cls) -> AnimationManager:
        """Process-wide animation registry for the design system."""
        global _INSTANCE
        if _INSTANCE is None:
            _INSTANCE = cls()
        return _INSTANCE

    def stop(self, owner: object, slot: str | None = None) -> None:
        """Stop one animation slot or every animation attached to owner."""
        entries = self._animations.get(owner)
        if not entries:
            return
        slots = tuple(entries) if slot is None else (slot,)
        for name in slots:
            animation = entries.pop(name, None)
            if animation is not None and shiboken6.isValid(animation):
                animation.stop()
        if not entries:
            self._animations.pop(owner, None)

    def animate_property(
        self,
        *,
        owner: object,
        slot: str,
        duration_ms: int,
        start: object,
        end: object,
        tick: Callable[[object], None],
        easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
    ) -> QVariantAnimation:
        """Start a QVariantAnimation, replacing any previous animation in slot."""
        self.stop(owner, slot)
        parent = owner if isinstance(owner, QWidget) and shiboken6.isValid(owner) else None
        animation = QVariantAnimation(parent)
        animation.setDuration(duration_ms)
        animation.setEasingCurve(easing)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.valueChanged.connect(tick)

        entries = self._animations.setdefault(owner, {})
        entries[slot] = animation

        def _cleanup() -> None:
            current = self._animations.get(owner, {}).get(slot)
            if current is animation:
                self._animations.get(owner, {}).pop(slot, None)

        animation.finished.connect(_cleanup)
        animation.start()
        return animation

    def animate_opacity(
        self,
        widget: QWidget,
        *,
        start: float,
        end: float,
        duration_ms: int = t.DURATION_BASE,
    ) -> QVariantAnimation:
        """Animate opacity through a replaceable QGraphicsOpacityEffect."""
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(start)
        widget.setGraphicsEffect(effect)

        def _tick(value: object) -> None:
            if shiboken6.isValid(effect):
                effect.setOpacity(_to_float(value))

        return self.animate_property(
            owner=widget,
            slot=_OPACITY_SLOT,
            duration_ms=duration_ms,
            start=start,
            end=end,
            tick=_tick,
        )

    def animate_shadow(
        self,
        shadow: _SafeShadowLike,
        target: t.ShadowSpec,
        duration_ms: int = t.DURATION_BASE,
    ) -> QVariantAnimation | None:
        """Animate a SafeShadow without touching invalid Qt effects."""
        widget = shadow.widget
        if not isinstance(widget, QWidget) or not shiboken6.isValid(widget):
            return None
        start_blur = shadow.blur_radius()
        start_y = shadow.y_offset()
        start_color = shadow.color()
        if start_blur is None or start_y is None or not isinstance(start_color, QColor):
            return None
        end_color = QColor(*target.rgba)

        def _tick(value: object) -> None:
            if not shiboken6.isValid(widget):
                self.stop(widget, _SHADOW_SLOT)
                return
            k = _to_float(value)
            shadow.set_blur_radius(start_blur + (target.blur - start_blur) * k)
            shadow.set_offset(0, start_y + (target.y_offset - start_y) * k)
            shadow.set_color(
                QColor(
                    round(start_color.red() + (end_color.red() - start_color.red()) * k),
                    round(start_color.green() + (end_color.green() - start_color.green()) * k),
                    round(start_color.blue() + (end_color.blue() - start_color.blue()) * k),
                    round(start_color.alpha() + (end_color.alpha() - start_color.alpha()) * k),
                )
            )

        return self.animate_property(
            owner=widget,
            slot=_SHADOW_SLOT,
            duration_ms=duration_ms,
            start=0.0,
            end=1.0,
            tick=_tick,
        )

    def animate_geometry(
        self,
        widget: QWidget,
        *,
        start: QRect,
        end: QRect,
        duration_ms: int = t.DURATION_BASE,
    ) -> QVariantAnimation:
        """Animate geometry for components that deliberately own absolute layout."""

        def _tick(value: object) -> None:
            if shiboken6.isValid(widget) and isinstance(value, QRect):
                widget.setGeometry(value)

        return self.animate_property(
            owner=widget,
            slot=_GEOMETRY_SLOT,
            duration_ms=duration_ms,
            start=start,
            end=end,
            tick=_tick,
        )

    def animate_scale(
        self,
        widget: QWidget,
        *,
        start: float = 1.0,
        end: float = 1.025,
        duration_ms: int = t.DURATION_BASE,
    ) -> QVariantAnimation:
        """Record a transform-only scale value without changing widget geometry."""

        def _tick(value: object) -> None:
            if shiboken6.isValid(widget):
                widget.setProperty("motionScale", _to_float(value))

        return self.animate_property(
            owner=widget,
            slot=_SCALE_SLOT,
            duration_ms=duration_ms,
            start=start,
            end=end,
            tick=_tick,
        )


_INSTANCE: AnimationManager | None = None


def _to_float(value: object) -> float:
    """QVariantAnimation emits Python numbers, but the signal type is object."""
    return float(value) if isinstance(value, int | float) else 0.0
