"""Атомы дизайн-системы: Button, Badge, StatusIndicator, Skeleton, SectionLabel."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from app.ui.theme import tokens as t
from app.ui.viewmodels import BadgeTone, StatusBadge


class ButtonKind(Enum):
    """Виды кнопок дизайн-системы."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    GHOST = "ghost"
    DANGER = "danger"


def _button_qss(kind: ButtonKind) -> str:
    """QSS кнопки строится при создании (после apply_theme), не при импорте."""
    styles: dict[ButtonKind, str] = {
        ButtonKind.PRIMARY: f"""
        QPushButton {{
            background: {t.BLUE}; color: white; border: none;
            border-radius: {t.RADIUS_CONTROL}px; padding: 0 16px; font-weight: 600;
        }}
        QPushButton:hover {{ background: #268FFF; }}
        QPushButton:pressed {{ background: #0071E3; }}
        QPushButton:disabled {{ background: {t.tint(t.BLUE, 0.35)}; color: white; }}
        """,
        ButtonKind.SECONDARY: f"""
        QPushButton {{
            background: {t.CARD_SOLID}; color: {t.TEXT};
            border: 1px solid {t.BORDER};
            border-radius: {t.RADIUS_CONTROL}px; padding: 0 16px; font-weight: 600;
        }}
        QPushButton:hover {{ border-color: rgba(10, 132, 255, 0.45); color: {t.BLUE}; }}
        QPushButton:pressed {{ background: {t.tint(t.BLUE, 0.10)}; }}
        QPushButton:disabled {{ color: {t.TEXT_TERTIARY}; }}
        """,
        ButtonKind.GHOST: f"""
        QPushButton {{
            background: transparent; color: {t.BLUE}; border: none;
            border-radius: {t.RADIUS_CONTROL}px; padding: 0 12px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {t.tint(t.BLUE, 0.10)}; }}
        QPushButton:pressed {{ background: {t.tint(t.BLUE, 0.18)}; }}
        QPushButton:disabled {{ color: {t.TEXT_TERTIARY}; }}
        """,
        ButtonKind.DANGER: f"""
        QPushButton {{
            background: {t.RED}; color: white; border: none;
            border-radius: {t.RADIUS_CONTROL}px; padding: 0 16px; font-weight: 600;
        }}
        QPushButton:hover {{ background: #FF5F55; }}
        QPushButton:pressed {{ background: #E63B31; }}
        """,
    }
    return styles[kind]


class Button(QPushButton):
    """Кнопка дизайн-системы (4 вида, единые размеры и радиусы)."""

    def __init__(
        self,
        text: str,
        kind: ButtonKind = ButtonKind.SECONDARY,
        *,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.kind = kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(t.BUTTON_HEIGHT_COMPACT if compact else t.BUTTON_HEIGHT)
        self.setStyleSheet(_button_qss(kind))


class Badge(QLabel):
    """Тонированная пилюля состояния (некликабельная)."""

    def __init__(self, badge: StatusBadge | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        if badge is not None:
            self.set_badge(badge)

    def set_badge(self, badge: StatusBadge) -> None:
        """Показать StatusBadge из viewmodels (цвет по тону)."""
        color = t.tone_color(badge.tone)
        self.setText(badge.label)
        if badge.detail:
            self.setToolTip(badge.detail)
        self.setStyleSheet(
            f"QLabel {{ background: {t.tint(color, 0.14)}; color: {color};"
            f" border-radius: {t.RADIUS_CHIP}px; padding: 0 10px;"
            f" font-size: {t.CAPTION_PT}pt; font-weight: 600; }}"
        )


class StatusIndicator(QWidget):
    """Живая точка состояния с пульсирующим ореолом (MUTED — статична)."""

    def __init__(self, tone: BadgeTone = BadgeTone.MUTED, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self._tone = tone
        self._phase = 0.0
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(t.DURATION_PULSE)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse)

    @property
    def tone(self) -> BadgeTone:
        """Текущий тон индикатора."""
        return self._tone

    def set_tone(self, tone: BadgeTone) -> None:
        """Сменить состояние (перезапускает пульс, MUTED гасит)."""
        self._tone = tone
        self._sync_pulse()
        self.update()

    def _on_pulse(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    def _sync_pulse(self) -> None:
        should_run = self._tone is not BadgeTone.MUTED and self.isVisible()
        running = self._pulse.state() == QVariantAnimation.State.Running
        if should_run and not running:
            self._pulse.start()
        elif not should_run and running:
            self._pulse.stop()
            self._phase = 0.0

    def showEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Пульс только пока виджет видим (производительность)."""
        super().showEvent(event)  # type: ignore[arg-type]
        self._sync_pulse()

    def hideEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Остановить анимацию у скрытого виджета."""
        super().hideEvent(event)  # type: ignore[arg-type]
        self._sync_pulse()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        """Точка 9px + расходящийся ореол."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        color = QColor(t.tone_color(self._tone))

        if self._tone is not BadgeTone.MUTED:
            halo = QColor(color)
            halo.setAlphaF(max(0.0, 0.35 * (1.0 - self._phase)))
            painter.setBrush(halo)
            painter.setPen(Qt.PenStyle.NoPen)
            radius = 4.5 + 6.0 * self._phase
            painter.drawEllipse(center, radius, radius)

        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 4.5, 4.5)
        painter.end()


class SkeletonBlock(QWidget):
    """Шиммер-заглушка на время первой загрузки (показывать ≤ 2 секунд)."""

    def __init__(self, width: int = 120, height: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._shift = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(1200)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._animation.valueChanged.connect(self._on_shift)

    def _on_shift(self, value: float) -> None:
        self._shift = float(value)
        self.update()

    def showEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Шиммер только на экране."""
        super().showEvent(event)  # type: ignore[arg-type]
        self._animation.start()

    def hideEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Стоп у скрытого виджета."""
        super().hideEvent(event)  # type: ignore[arg-type]
        self._animation.stop()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        """Полоса с бегущим бликом (цвета — из активной палитры темы)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(*t.SKELETON_BASE_RGBA))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 6, 6)

        glare_alpha = 110 if t.CURRENT_THEME == "light" else 34
        painter.setBrush(QColor(255, 255, 255, glare_alpha))
        band_width = max(24, self.width() // 3)
        x = int((self.width() + band_width) * self._shift) - band_width
        painter.drawRoundedRect(x, 0, band_width, self.height(), 6, 6)
        painter.end()


class SectionLabel(QLabel):
    """Подпись секции: CAPTION, UPPERCASE, разрядка."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
            f" font-weight: 600; letter-spacing: 0.6px; background: transparent; }}"
        )
