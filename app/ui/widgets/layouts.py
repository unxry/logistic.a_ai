"""FlowLayout — перенос элементов на новую строку (чипы причин, теги).

Классический Qt-паттерн: минимальная ширина ряда равна ширине одного
элемента, а не суммы всех — длинные наборы чипов не распирают карточки.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


def clear_layout(layout: QLayout) -> None:
    """Удалить все виджеты layout'а (единый безопасный паттерн очистки)."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class FlowLayout(QLayout):
    """Layout с переносом по ширине (h-spacing/v-spacing из дизайн-сетки)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        h_spacing: int = 6,
        v_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt API)
        """Добавить элемент."""
        self._items.append(item)

    def count(self) -> int:
        """Число элементов."""
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt API)
        """Элемент по индексу (None за границами)."""
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt API)
        """Изъять элемент по индексу."""
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 (Qt API)
        """Не расширяется самостоятельно."""
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt API)
        """Высота зависит от ширины (перенос строк)."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt API)
        """Высота при заданной ширине."""
        return self._layout(QRect(0, 0, width, 0), apply_geometry=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt API)
        """Разложить элементы с переносом."""
        super().setGeometry(rect)
        self._layout(rect, apply_geometry=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        """Предпочтительный размер."""
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt API)
        """Минимум — самый широкий элемент (не сумма!)."""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _layout(self, rect: QRect, *, apply_geometry: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        row_height = 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > effective.right() + 1 and row_height > 0:
                x = effective.x()
                y += row_height + self._v_spacing
                row_height = 0
            if apply_geometry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h_spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()
