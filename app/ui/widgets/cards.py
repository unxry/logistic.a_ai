"""Поверхности дизайн-системы: GlassCard, HoverCard, MetricCard, Empty/Error.

Stage 9.8: три уровня тени REST/HOVER/ACTIVE, hover подсвечивает фон карточки
(геометрия не меняется — ничего не прыгает), пустые состояния — с мягкой
иллюстрацией-кругом.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QEnterEvent, QHideEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from app.ui.theme import animate_shadow, apply_shadow, count_up
from app.ui.theme import tokens as t
from app.ui.theme.animation_manager import AnimationManager
from app.ui.widgets.atoms import Button, ButtonKind, SectionLabel
from app.ui.widgets.charts import Sparkline


class GlassCard(QFrame):
    """Базовая «стеклянная» карточка: полупрозрачная поверхность + тень REST."""

    def __init__(self, parent: QWidget | None = None, *, radius: int = t.RADIUS_CARD) -> None:
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self._radius = radius
        self._set_surface(background=t.CARD, border=t.BORDER)
        self._shadow = apply_shadow(self, t.SHADOW_RESTING)

    def body(self, margin: int = t.SPACE_XL, spacing: int = t.SPACE_M) -> QVBoxLayout:
        """Стандартный внутренний layout карточки."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(spacing)
        return layout

    def _set_surface(self, *, background: str, border: str) -> None:
        self.setStyleSheet(
            f"QFrame#GlassCard {{ background: {background}; border: 1px solid {border};"
            f" border-radius: {self._radius}px; }}"
        )


class HoverCard(GlassCard):
    """Интерактивная карточка: hover — подсветка фона, синяя кромка и подъём
    тени REST → HOVER; нажатие прижимает тень к ACTIVE. Геометрия неизменна."""

    def __init__(self, parent: QWidget | None = None, *, radius: int = t.RADIUS_CARD) -> None:
        super().__init__(parent, radius=radius)
        self._hover_targets: list[QWidget] = []
        self._hovered = False

    def reveal_on_hover(self, widget: QWidget) -> None:
        """Зарегистрировать виджет, появляющийся только при наведении."""
        widget.setVisible(True)
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        self._hover_targets.append(widget)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 (Qt API)
        """Подъём: тень HOVER + светлее фон + синяя кромка + показ действий."""
        super().enterEvent(event)
        self._hovered = True
        animate_shadow(self._shadow, t.SHADOW_LIFTED)
        AnimationManager.instance().animate_scale(self, start=1.0, end=1.025)
        self._set_surface(background=t.CARD_HOVER, border="rgba(10, 132, 255, 0.35)")
        for widget in self._hover_targets:
            AnimationManager.instance().animate_opacity(widget, start=0.0, end=1.0)

    def leaveEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Возврат в покой."""
        super().leaveEvent(event)  # type: ignore[arg-type]
        self._hovered = False
        animate_shadow(self._shadow, t.SHADOW_RESTING)
        AnimationManager.instance().animate_scale(self, start=1.025, end=1.0)
        self._set_surface(background=t.CARD, border=t.BORDER)
        for widget in self._hover_targets:
            AnimationManager.instance().animate_opacity(widget, start=1.0, end=0.0)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        """Нажатие прижимает карточку: тень ACTIVE (быстро)."""
        super().mousePressEvent(event)
        animate_shadow(self._shadow, t.SHADOW_ACTIVE, t.DURATION_FAST)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        """Отпускание возвращает тень HOVER (или REST, если увели курсор)."""
        super().mouseReleaseEvent(event)
        target = t.SHADOW_LIFTED if self._hovered else t.SHADOW_RESTING
        animate_shadow(self._shadow, target, t.DURATION_FAST)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 (Qt API)
        """Hidden cards must not keep hover/shadow animations alive."""
        AnimationManager.instance().stop(self)
        for widget in self._hover_targets:
            AnimationManager.instance().stop(widget)
        super().hideEvent(event)

    def closeEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Release animation references before Qt destroys child effects."""
        AnimationManager.instance().stop(self)
        for widget in self._hover_targets:
            AnimationManager.instance().stop(widget)
        super().closeEvent(event)  # type: ignore[arg-type]


class MetricCard(HoverCard):
    """Метрика: подпись CAPTION + значение DISPLAY (count-up) + мини-график.

    Наследует hover-реакцию: дашборд отвечает светом на движение курсора.
    """

    def __init__(
        self,
        caption: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = self.body(spacing=t.SPACE_S)
        layout.addWidget(SectionLabel(caption))
        self._value = QLabel("—")
        self._value.setStyleSheet(
            f"QLabel {{ font-size: {t.DISPLAY_PT - 6}pt; font-weight: 700;"
            f" color: {t.TEXT}; background: transparent; }}"
        )
        layout.addWidget(self._value)
        self._hint = QLabel("")
        self._hint.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
            f" background: transparent; }}"
        )
        self._hint.setVisible(False)
        layout.addWidget(self._hint)
        self._sparkline = Sparkline(self)
        self._sparkline.setVisible(False)
        layout.addWidget(self._sparkline)
        layout.addStretch(1)

    def set_text_value(self, value: str, hint: str = "") -> None:
        """Показать готовую строку (деньги приходят отформатированными)."""
        self._value.setText(value)
        self._set_hint(hint)

    def animate_value(self, target: int, formatter: Callable[[int], str] = str) -> None:
        """Count-up для целых значений."""
        count_up(self._value, target, formatter=formatter)

    def show_series(self, values: Sequence[float], color: str = t.BLUE) -> None:
        """Подключить тонкий график (только при реальном ряде данных)."""
        self._sparkline.set_values(values, color=color)
        self._sparkline.setVisible(True)

    def _set_hint(self, hint: str) -> None:
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))


class IllustrationBadge(QWidget):
    """Минимальная иллюстрация пустого состояния: глиф в мягких кругах тона."""

    def __init__(self, glyph: str, color: str = t.BLUE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._color = QColor(color)
        self._glyph = QLabel(glyph, self)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setGeometry(0, 0, 96, 96)
        self._glyph.setStyleSheet("QLabel { font-size: 30pt; background: transparent; }")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        """Два концентрических круга-ореола под глифом."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        center = self.rect().center()
        outer = QColor(self._color)
        outer.setAlphaF(0.08)
        painter.setBrush(outer)
        painter.drawEllipse(center, 47, 47)
        inner = QColor(self._color)
        inner.setAlphaF(0.14)
        painter.setBrush(inner)
        painter.drawEllipse(center, 34, 34)
        painter.end()


class EmptyState(QWidget):
    """Пустое состояние: иллюстрация, заголовок, подсказка, действие."""

    def __init__(
        self,
        glyph: str,
        title: str,
        hint: str,
        *,
        action: Button | None = None,
        tone_color: str = t.BLUE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.SPACE_XXL, t.SPACE_XXL * 2, t.SPACE_XXL, t.SPACE_XXL * 2)
        layout.setSpacing(t.SPACE_S)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(
            IllustrationBadge(glyph, tone_color, self), alignment=Qt.AlignmentFlag.AlignHCenter
        )
        layout.addSpacing(t.SPACE_S)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 600;"
            f" color: {t.TEXT}; background: transparent; }}"
        )
        layout.addWidget(title_label)

        hint_label = QLabel(hint)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}"
        )
        layout.addWidget(hint_label)

        if action is not None:
            layout.addSpacing(t.SPACE_S)
            layout.addWidget(action, alignment=Qt.AlignmentFlag.AlignCenter)


class ErrorState(EmptyState):
    """Ошибка: всегда объясняет, что делать, и предлагает повторить."""

    def __init__(
        self,
        title: str,
        hint: str,
        *,
        on_retry: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        retry: Button | None = None
        if on_retry is not None:
            retry = Button("Повторить", ButtonKind.SECONDARY)
            retry.clicked.connect(on_retry)
        super().__init__("⚠️", title, hint, action=retry, tone_color=t.ORANGE, parent=parent)
