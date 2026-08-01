"""База страниц: заголовок TITLE + прокручиваемое содержимое на сетке 4pt."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.theme import reveal_scrollbar_on_scroll
from app.ui.theme import tokens as t
from app.ui.viewmodels import DashboardSnapshot


class Page(QWidget):
    """Страница приложения: единые поля, заголовок и скролл-невидимка."""

    def __init__(self, page_id: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.setObjectName("Page")
        self.setStyleSheet("QWidget#Page { background: transparent; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SPACE_PAGE, t.SPACE_PAGE, t.SPACE_PAGE, 0)
        outer.setSpacing(t.SPACE_L)

        heading = QLabel(title, self)
        heading.setStyleSheet(
            f"QLabel {{ font-size: {t.TITLE_PT}pt; font-weight: 700;"
            f" letter-spacing: -0.3px; background: transparent; }}"
        )
        outer.addWidget(heading)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        reveal_scrollbar_on_scroll(self._scroll)
        outer.addWidget(self._scroll, stretch=1)

        self.content = QWidget(self)
        self.content.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, t.SPACE_XS, t.SPACE_PAGE)
        self.content_layout.setSpacing(t.SPACE_L)
        self._scroll.setWidget(self.content)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Обновиться из снапшота дашборда (страницы переопределяют)."""
