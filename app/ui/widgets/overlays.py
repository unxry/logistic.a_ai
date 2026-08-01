"""Оверлеи: Modal (macOS-sheet), Toast/ToastHost, CommandPalette (⌘K).

Все оверлеи живут ПОВЕРХ главного окна (parent=window), затемняют фон,
закрываются Esc и кликом мимо. Stage 9.8: Modal ведёт себя как нативный
sheet (выезжает сверху с fade), палитра — в духе Raycast: иконки, хоткеи,
подсветка совпадения, открытие scale 0.98 → 1.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import shiboken6
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QKeyEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import apply_shadow, fade_in, reveal_scrollbar_on_scroll
from app.ui.theme import tokens as t
from app.ui.viewmodels import BadgeTone


class Overlay(QWidget):
    """Затемняющий слой поверх окна; Esc и клик мимо закрывают."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(10, 10, 12, 0.38);")
        self.hide()

    def open(self) -> None:
        """Показать оверлей на весь родитель с fade."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        fade_in(self, t.DURATION_BASE)

    def close_overlay(self) -> None:
        """Закрыть (без анимации: закрытие должно быть мгновенным)."""
        self.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        """Esc закрывает."""
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        """Клик по затемнению (мимо контента) закрывает."""
        if self.childAt(event.position().toPoint()) is None:
            self.close_overlay()
            return
        super().mousePressEvent(event)


def _slide_panel_in(panel: QWidget, final_x: int, final_y: int, *, offset: int) -> None:
    """Sheet-появление панели: выезд сверху на ``offset`` px + fade.

    Двигается только сама панель (геометрия оверлея не меняется).
    """
    effect = QGraphicsOpacityEffect(panel)
    effect.setOpacity(0.0)
    panel.setGraphicsEffect(effect)
    animation = QVariantAnimation(panel)
    animation.setDuration(t.DURATION_ENTER)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)

    def _tick(value: float) -> None:
        if not shiboken6.isValid(effect):
            animation.stop()
            return
        k = float(value)
        effect.setOpacity(k)
        panel.move(final_x, final_y - round(offset * (1.0 - k)))

    def _finish() -> None:
        if shiboken6.isValid(panel):
            panel.move(final_x, final_y)
            if panel.graphicsEffect() is effect:
                panel.setGraphicsEffect(None)  # type: ignore[arg-type]

    animation.valueChanged.connect(_tick)
    animation.finished.connect(_finish)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class Modal(Overlay):
    """Модальная панель в духе macOS Sheet: выезжает сверху, широкие поля.

    Используется для AI Explanation — «почему выбран груз»."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._panel = QFrame(self)
        self._panel.setObjectName("ModalPanel")
        self._panel.setStyleSheet(
            f"QFrame#ModalPanel {{ background: {t.CARD_SOLID};"
            f" border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_HERO}px; }}"
        )
        apply_shadow(self._panel, t.SHADOW_LIFTED)
        self._layout = QVBoxLayout(self._panel)
        margin = t.SPACE_XXL + t.SPACE_XS
        self._layout.setContentsMargins(margin, margin, margin, margin)
        self._layout.setSpacing(t.SPACE_L)
        self._title = QLabel("")
        self._title.setStyleSheet(
            f"QLabel {{ font-size: {t.TITLE_PT - 2}pt; font-weight: 700;"
            f" letter-spacing: -0.2px; background: transparent; }}"
        )
        self._layout.addWidget(self._title)
        self._content: QWidget | None = None

    def show_content(self, title: str, content: QWidget) -> None:
        """Открыть sheet с новым содержимым."""
        if self._content is not None:
            self._layout.removeWidget(self._content)
            self._content.deleteLater()
        self._content = content
        self._title.setText(title)
        self._layout.addWidget(content)
        self.open()
        self._panel.adjustSize()
        x, y = self._panel_position()
        self._panel.move(x, y)
        _slide_panel_in(self._panel, x, y, offset=26)
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API)
        """Держать sheet у верхней кромки по центру."""
        super().resizeEvent(event)
        x, y = self._panel_position()
        self._panel.move(x, y)

    def _panel_position(self) -> tuple[int, int]:
        width = min(560, self.width() - t.SPACE_XXL * 2)
        self._panel.setFixedWidth(max(340, width))
        self._panel.adjustSize()
        x = (self.width() - self._panel.width()) // 2
        y = max(t.SPACE_XXL * 2, self.height() // 9)
        return x, y


class Toast(QFrame):
    """Одно уведомление: тонированная полоска-акцент + заголовок + текст."""

    def __init__(self, title: str, body: str, tone: BadgeTone, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        color = t.tone_color(tone)
        self.setStyleSheet(
            f"QFrame#Toast {{ background: {t.CARD_SOLID}; border: 1px solid {t.BORDER};"
            f" border-left: 3px solid {color}; border-radius: 12px; }}"
        )
        apply_shadow(self, t.SHADOW_LIFTED)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.SPACE_L, t.SPACE_M, t.SPACE_L, t.SPACE_M)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("QLabel { font-weight: 600; background: transparent; }")
        layout.addWidget(title_label)
        if body:
            body_label = QLabel(body)
            body_label.setWordWrap(True)
            body_label.setStyleSheet(
                f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
                f" background: transparent; }}"
            )
            layout.addWidget(body_label)
        self.setFixedWidth(320)


class ToastHost(QWidget):
    """Стек тостов в правом нижнем углу окна (≤ 3, автозакрытие)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, t.SPACE_XXL, t.SPACE_XXL)
        self._layout.setSpacing(t.SPACE_S)
        self._layout.addStretch(1)
        self._toasts: list[Toast] = []
        self.hide()

    def show_toast(self, title: str, body: str = "", tone: BadgeTone = BadgeTone.OK) -> None:
        """Показать тост (лишние сверх трёх закрываются немедленно)."""
        while len(self._toasts) >= 3:
            self._dismiss(self._toasts[0])
        toast = Toast(title, body, tone, self)
        self._toasts.append(toast)
        self._layout.addWidget(toast, alignment=Qt.AlignmentFlag.AlignRight)
        self._reposition()
        self.show()
        self.raise_()
        fade_in(toast, t.DURATION_BASE)
        # Таймер парентован тосту: умирает вместе с ним (никаких «выстрелов»
        # по удалённым виджетам после закрытия окна).
        timer = QTimer(toast)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._dismiss(toast))
        timer.start(t.TOAST_LIFETIME_MS)

    def relayout(self) -> None:
        """Пересчитать позицию при изменении размера окна."""
        self._reposition()

    def _dismiss(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            toast.hide()
            toast.deleteLater()
        if not self._toasts:
            self.hide()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = 320 + t.SPACE_XXL * 2
        self.setGeometry(parent.width() - width, 0, width, parent.height())


@dataclass(frozen=True, slots=True)
class Command:
    """Команда палитры (⌘K)."""

    id: str
    title: str
    run: Callable[[], None]
    subtitle: str = ""
    shortcut: str = ""
    icon: str = ""
    keywords: tuple[str, ...] = field(default=())


def _highlight(title: str, needle: str) -> str:
    """Подсветить совпадение запроса в заголовке (rich text, HTML-безопасно)."""
    if not needle:
        return html.escape(title)
    index = title.casefold().find(needle.casefold())
    if index < 0:
        return html.escape(title)
    before = html.escape(title[:index])
    match = html.escape(title[index : index + len(needle)])
    after = html.escape(title[index + len(needle) :])
    return f"{before}<span style='color: {t.BLUE}; font-weight: 600;'>{match}</span>{after}"


class _PaletteRow(QWidget):
    """Строка палитры: иконка + заголовок (с подсветкой) + хоткей справа."""

    def __init__(self, command: Command, query: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.SPACE_S, 0, t.SPACE_S, 0)
        layout.setSpacing(t.SPACE_M)

        icon = QLabel(command.icon or "•", self)
        icon.setFixedWidth(26)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("QLabel { font-size: 12pt; background: transparent; }")
        layout.addWidget(icon)

        text_column = QVBoxLayout()
        text_column.setSpacing(0)
        title = QLabel(_highlight(command.title, query), self)
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(
            f"QLabel {{ color: {t.TEXT}; font-weight: 500; background: transparent; }}"
        )
        text_column.addWidget(title)
        if command.subtitle:
            subtitle = QLabel(command.subtitle, self)
            subtitle.setStyleSheet(
                f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT - 1}pt;"
                f" background: transparent; }}"
            )
            text_column.addWidget(subtitle)
        layout.addLayout(text_column, stretch=1)

        if command.shortcut:
            hotkey = QLabel(command.shortcut, self)
            hotkey.setStyleSheet(
                f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
                f" background: {t.tint(t.MUTED, 0.10)}; border-radius: 6px;"
                f" padding: 2px 7px; font-weight: 600; }}"
            )
            layout.addWidget(hotkey)


class CommandPalette(Overlay):
    """Палитра команд в духе Raycast: поиск + список, Enter выполняет."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._commands: tuple[Command, ...] = ()

        self._panel = QFrame(self)
        self._panel.setObjectName("PalettePanel")
        self._panel.setStyleSheet(
            f"QFrame#PalettePanel {{ background: {t.CARD_SOLID};"
            f" border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_CARD}px; }}"
        )
        apply_shadow(self._panel, t.SHADOW_LIFTED)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(t.SPACE_S, t.SPACE_S, t.SPACE_S, t.SPACE_S)
        panel_layout.setSpacing(t.SPACE_XS)

        self._search = QLineEdit(self._panel)
        self._search.setPlaceholderText("Что сделать? Например: «найти груз»")
        self._search.setStyleSheet(
            f"""
            QLineEdit {{
                background: transparent; border: none;
                font-size: {t.HEADLINE_PT}pt; padding: 10px 12px 12px 12px;
                selection-background-color: {t.tint(t.BLUE, 0.25)};
            }}
            QLineEdit:focus {{ border: none; padding: 10px 12px 12px 12px; }}
            """
        )
        self._search.textChanged.connect(self._refilter)
        panel_layout.addWidget(self._search)

        separator = QFrame(self._panel)
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"QFrame {{ background: {t.BORDER}; border: none; }}")
        panel_layout.addWidget(separator)

        self._list = QListWidget(self._panel)
        self._list.setStyleSheet(
            f"""
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ border-radius: {t.RADIUS_CONTROL}px; }}
            QListWidget::item:hover {{ background: {t.tint(t.MUTED, 0.08)}; }}
            QListWidget::item:selected {{ background: {t.tint(t.BLUE, 0.12)}; }}
            """
        )
        self._list.itemActivated.connect(self._run_item)
        reveal_scrollbar_on_scroll(self._list)
        panel_layout.addWidget(self._list)

    def set_commands(self, commands: Sequence[Command]) -> None:
        """Зарегистрировать доступные команды."""
        self._commands = tuple(commands)

    def open_palette(self) -> None:
        """Открыть с пустым запросом и фокусом в поиске (scale 0.98 → 1)."""
        self._search.clear()
        self._refilter("")
        self.open()
        self._position_panel(animate=True)
        self._search.setFocus(Qt.FocusReason.PopupFocusReason)

    def visible_commands(self) -> tuple[Command, ...]:
        """Команды, видимые при текущем фильтре (для тестов и подсказок)."""
        result: list[Command] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            command = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(command, Command):
                result.append(command)
        return tuple(result)

    def run_selected(self) -> None:
        """Выполнить выбранную команду (Enter)."""
        item = self._list.currentItem()
        if item is not None:
            self._run_item(item)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        """Enter — выполнить; стрелки идут в список; Esc — базовое закрытие."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.run_selected()
            return
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self._list.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API)
        """Панель — по верхней трети, как в Raycast."""
        super().resizeEvent(event)
        self._position_panel(animate=False)

    def _position_panel(self, *, animate: bool) -> None:
        width = max(360, min(600, self.width() - t.SPACE_XXL * 2))
        height = min(400, max(240, self.height() // 2))
        x = (self.width() - width) // 2
        y = max(t.SPACE_XXL, self.height() // 6)
        if not animate:
            self._panel.setGeometry(x, y, width, height)
            return
        self._panel.setGeometry(x, y, width, height)
        self._animate_open(x, y, width, height)

    def _animate_open(self, x: int, y: int, width: int, height: int) -> None:
        """Открытие: scale 0.98 → 1.00 + opacity 0 → 1 вокруг центра панели."""
        panel = self._panel
        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(0.0)
        panel.setGraphicsEffect(effect)
        animation = QVariantAnimation(panel)
        animation.setDuration(t.DURATION_BASE)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)

        def _tick(value: float) -> None:
            if not shiboken6.isValid(effect):
                animation.stop()
                return
            k = float(value)
            effect.setOpacity(k)
            scale = 0.98 + 0.02 * k
            w = round(width * scale)
            h = round(height * scale)
            panel.setGeometry(x + (width - w) // 2, y + (height - h) // 2, w, h)

        def _finish() -> None:
            if shiboken6.isValid(panel):
                panel.setGeometry(x, y, width, height)
                if panel.graphicsEffect() is effect:
                    panel.setGraphicsEffect(None)  # type: ignore[arg-type]

        animation.valueChanged.connect(_tick)
        animation.finished.connect(_finish)
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _refilter(self, query: str) -> None:
        needle = query.casefold().strip()
        self._list.clear()
        for command in self._commands:
            haystack = " ".join((command.title, command.subtitle, *command.keywords)).casefold()
            if needle and needle not in haystack:
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, command)
            item.setSizeHint(QSize(0, 46 if command.subtitle else 38))
            self._list.addItem(item)
            self._list.setItemWidget(item, _PaletteRow(command, query.strip(), self._list))
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _run_item(self, item: QListWidgetItem) -> None:
        command = item.data(Qt.ItemDataRole.UserRole)
        self.close_overlay()
        if isinstance(command, Command):
            command.run()
