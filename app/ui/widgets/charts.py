"""Графика дизайн-системы: Sparkline (тонкий график) и ScoreRing (AI Score).

Только paintEvent + токены: без осей, сеток и библиотек. Stage 9.8 —
«живые» окончания: светящаяся точка на конце дуги/линии дышит как в Apple
Activity Rings; линия Sparkline отрисовывается анимацией. Все циклы
останавливаются у невидимых виджетов (show/hideEvent).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QLabel, QWidget

from app.ui.theme import breathing, count_up
from app.ui.theme import tokens as t


class Sparkline(QWidget):
    """Мини-график: линия 1.5px, заливка ≤ 12% альфы, дышащая точка на конце."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        self._values: tuple[float, ...] = ()
        self._color = QColor(t.BLUE)
        self._reveal = 1.0  # доля линии, уже отрисованная анимацией
        self._phase = 0.0  # фаза дыхания конечной точки
        self._pulse = breathing(self)
        self._pulse.valueChanged.connect(self._on_pulse)

    def set_values(self, values: Sequence[float], *, color: str = t.BLUE) -> None:
        """Задать ряд (минимум 2 точки — иначе график скрывает себя).

        Новый ряд отрисовывается анимацией слева направо; идентичный ряд
        не перезапускает отрисовку (событие + снапшот не дублируют работу).
        """
        new_values = tuple(float(v) for v in values)
        new_color = QColor(color)
        if new_values == self._values and new_color == self._color:
            return
        self._values = new_values
        self._color = new_color
        self._animate_reveal()
        self._sync_pulse()
        self.update()

    def showEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Дыхание точки — только на экране."""
        super().showEvent(event)  # type: ignore[arg-type]
        self._sync_pulse()

    def hideEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Стоп всех циклов у скрытого виджета."""
        super().hideEvent(event)  # type: ignore[arg-type]
        self._sync_pulse()

    def _on_pulse(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    def _sync_pulse(self) -> None:
        should_run = len(self._values) >= 2 and self.isVisible()
        running = self._pulse.state() == QVariantAnimation.State.Running
        if should_run and not running:
            self._pulse.start()
        elif not should_run and running:
            self._pulse.stop()
            self._phase = 0.0

    def _animate_reveal(self) -> None:
        if not self.isVisible():
            self._reveal = 1.0  # за кадром рисуемся сразу, без анимации
            return
        animation = QVariantAnimation(self)
        animation.setDuration(t.DURATION_COUNT)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)

        def _tick(value: float) -> None:
            self._reveal = float(value)
            self.update()

        animation.valueChanged.connect(_tick)
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        """Сглаженная кривая по точкам ряда + живая конечная точка."""
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = float(self.width())
        height = float(self.height())
        pad_x = 8.0  # запас справа под ореол конечной точки
        pad_y = 6.0
        low = min(self._values)
        high = max(self._values)
        span = (high - low) or 1.0
        step = (width - pad_x * 2) / (len(self._values) - 1)

        points = [
            QPointF(
                pad_x + i * step,
                pad_y + (height - pad_y * 2) * (1.0 - (v - low) / span),
            )
            for i, v in enumerate(self._values)
        ]

        # Сглаживание: квадратичные сегменты через середины отрезков.
        path = QPainterPath(points[0])
        for i in range(1, len(points)):
            mid = QPointF(
                (points[i - 1].x() + points[i].x()) / 2,
                (points[i - 1].y() + points[i].y()) / 2,
            )
            path.quadTo(points[i - 1], mid)
        path.quadTo(points[-1], points[-1])

        # Отрисовка линии анимацией: клип слева направо по _reveal.
        if self._reveal < 1.0:
            painter.setClipRect(QRectF(0, 0, width * self._reveal, height))

        fill = QPainterPath(path)
        fill.lineTo(points[-1].x(), height)
        fill.lineTo(points[0].x(), height)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, height)
        top = QColor(self._color)
        top.setAlphaF(0.12)
        bottom = QColor(self._color)
        bottom.setAlphaF(0.0)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(fill, gradient)

        pen = QPen(self._color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setClipping(False)

        # Дышащая конечная точка: проявляется на последних 15% отрисовки.
        dot_alpha = max(0.0, (self._reveal - 0.85) / 0.15)
        if dot_alpha > 0.0:
            tip = points[-1]
            halo = QColor(self._color)
            halo.setAlphaF(dot_alpha * (0.30 - 0.16 * self._phase))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            radius = 4.0 + 2.5 * self._phase
            painter.drawEllipse(tip, radius, radius)
            core = QColor(self._color)
            core.setAlphaF(dot_alpha)
            painter.setBrush(core)
            painter.drawEllipse(tip, 2.4, 2.4)
        painter.end()


class ScoreRing(QWidget):
    """AI Score: дуга 270° с мягким glow и набегающим числом в центре.

    Цвет по порогам дизайн-системы: <50 ORANGE, ≥50 BLUE, ≥85 GREEN.
    На конце дуги — светящаяся точка, пульсирующая как в Apple Activity
    Rings (только пока виджет видим).
    """

    def __init__(self, parent: QWidget | None = None, *, diameter: int = 96) -> None:
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._score = 0
        self._shown = 0.0
        self._phase = 0.0
        self._pulse = breathing(self)
        self._pulse.valueChanged.connect(self._on_pulse)
        self._number = QLabel("0", self)
        self._number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._number.setGeometry(0, 0, diameter, diameter)
        self._number.setStyleSheet(
            f"QLabel {{ font-size: {t.DISPLAY_PT - 8}pt; font-weight: 700;"
            f" color: {t.TEXT}; background: transparent; }}"
        )

    @property
    def score(self) -> int:
        """Текущее значение 0–100."""
        return self._score

    def set_score(self, score: int, *, animate: bool = True) -> None:
        """Показать балл (с count-up и плавным заполнением дуги)."""
        self._score = max(0, min(100, score))
        if animate:
            animation = count_up(self._number, self._score)
            animation.valueChanged.connect(self._on_progress)
        else:
            self._shown = float(self._score)
            self._number.setText(str(self._score))
            self.update()
        self._sync_pulse()

    def showEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Пульс конечной точки — только на экране."""
        super().showEvent(event)  # type: ignore[arg-type]
        self._sync_pulse()

    def hideEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Стоп анимации у скрытого виджета."""
        super().hideEvent(event)  # type: ignore[arg-type]
        self._sync_pulse()

    def _on_progress(self, value: int) -> None:
        self._shown = float(int(value))
        self.update()

    def _on_pulse(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    def _sync_pulse(self) -> None:
        should_run = self._score > 0 and self.isVisible()
        running = self._pulse.state() == QVariantAnimation.State.Running
        if should_run and not running:
            self._pulse.start()
        elif not should_run and running:
            self._pulse.stop()
            self._phase = 0.0

    def _color(self) -> QColor:
        if self._score >= 85:
            return QColor(t.GREEN)
        if self._score >= 50:
            return QColor(t.BLUE)
        return QColor(t.ORANGE)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        """Трек + прогресс-дуга + glow + живая точка на конце дуги."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        stroke = 7.0
        rect = QRectF(stroke, stroke, self.width() - stroke * 2, self.height() - stroke * 2)
        start_angle = 225 * 16  # дуга 270°: от 225° по часовой
        span_full = -270 * 16
        color = self._color()

        track_color = (
            QColor(255, 255, 255, 26) if t.CURRENT_THEME == "dark" else QColor(9, 17, 33, 20)
        )
        track = QPen(track_color, stroke)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, start_angle, span_full)

        progress = int(span_full * self._shown / 100.0)
        if progress != 0:
            glow = QColor(color)
            glow.setAlphaF(0.22)
            glow_pen = QPen(glow, stroke + 6)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow_pen)
            painter.drawArc(rect, start_angle, progress)

            pen = QPen(color, stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, start_angle, progress)

            self._draw_tip(painter, rect, color)
        painter.end()

    def _draw_tip(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        """Светящаяся точка на конце дуги (позиция — угол текущего прогресса)."""
        angle = math.radians(225.0 - 270.0 * self._shown / 100.0)
        radius = rect.width() / 2.0
        center = rect.center()
        tip = QPointF(
            center.x() + radius * math.cos(angle),
            center.y() - radius * math.sin(angle),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        halo = QColor(color)
        halo.setAlphaF(0.38 - 0.20 * self._phase)
        painter.setBrush(halo)
        halo_radius = 6.5 + 2.5 * self._phase
        painter.drawEllipse(tip, halo_radius, halo_radius)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(tip, 2.6, 2.6)
