"""Timeline активности: вертикальная линия, цветные точки, время справа."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.theme import tokens as t
from app.ui.viewmodels import EventRowViewModel
from app.ui.widgets.layouts import clear_layout

_SEVERITY_COLOR: dict[str, str] = {
    "success": t.GREEN,
    "warning": t.ORANGE,
    "critical": t.RED,
    "info": t.BLUE,
}


class _Dot(QWidget):
    """Точка события с хвостом линии вниз."""

    def __init__(self, color: str, *, last: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._last = last
        self.setFixedWidth(16)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        """Точка 8px + соединительная линия к следующему событию."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = 10.0
        if not self._last:
            painter.setPen(QColor(9, 17, 33, 26))
            painter.drawLine(int(cx), int(cy) + 6, int(cx), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(int(cx) - 4, int(cy) - 4, 8, 8)
        painter.end()


class Timeline(QWidget):
    """Список событий журнала (EventRowViewModel) в виде таймлайна."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def set_events(self, rows: Sequence[EventRowViewModel]) -> None:
        """Перерисовать таймлайн под новый список."""
        clear_layout(self._layout)
        for index, row in enumerate(rows):
            self._layout.addWidget(self._make_row(row, last=index == len(rows) - 1))
        self._layout.addStretch(1)

    def rows_count(self) -> int:
        """Число строк (для тестов)."""
        return max(0, self._layout.count() - 1)

    def _make_row(self, row: EventRowViewModel, *, last: bool) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, t.SPACE_M if not last else 0)
        layout.setSpacing(t.SPACE_S)

        dot = _Dot(_SEVERITY_COLOR.get(row.severity, t.MUTED), last=last, parent=container)
        layout.addWidget(dot)

        text_column = QVBoxLayout()
        text_column.setSpacing(1)
        title = QLabel(row.title)
        title.setWordWrap(True)
        title.setStyleSheet("QLabel { background: transparent; }")
        text_column.addWidget(title)
        if row.source:
            source = QLabel(row.source)
            source.setStyleSheet(
                f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT}pt;"
                f" background: transparent; }}"
            )
            text_column.addWidget(source)
        if row.details:
            details = QLabel(row.details)
            details.setStyleSheet(
                f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT}pt;"
                f" background: transparent; }}"
            )
            text_column.addWidget(details)
        layout.addLayout(text_column, stretch=1)

        time_label = QLabel(row.time_label)
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        time_label.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
            f" background: transparent; }}"
        )
        layout.addWidget(time_label)
        return container
