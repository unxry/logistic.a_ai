"""Sidebar — стеклянная навигация приложения (7 разделов, статус AI).

Stage 9.8: вертикальный световой градиент с внутренним бликом, статус-пилюля
приложения сверху, плавающая капсула активного раздела (плавно скользит между
пунктами, в духе Raycast) и футер-карточка с версией и бейджами связей.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QRect,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import tokens as t
from app.ui.viewmodels import BadgeTone
from app.ui.widgets.atoms import StatusIndicator
from app.ui.widgets.layouts import FlowLayout

#: Разделы приложения (id, глиф, подпись) — порядок из ТЗ.
NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "🚚", "Dashboard"),
    ("cargo", "📦", "Грузы"),
    ("favorites", "⭐", "Избранное"),
    ("vehicle", "🚗", "Машина"),
    ("search", "🔍", "Поиск"),
    ("analytics", "📊", "Аналитика"),
    ("notifications", "🕘", "Уведомления"),
    ("sources", "🔌", "Источники"),
    ("settings", "⚙️", "Настройки"),
)

#: Подпись статус-пилюли по тону приложения.
_PILL_TEXT: dict[BadgeTone, str] = {
    BadgeTone.OK: "Online · AI активен",
    BadgeTone.WARNING: "Запускается…",
    BadgeTone.ERROR: "Оффлайн",
    BadgeTone.MUTED: "Ожидание",
}


def _item_qss() -> str:
    """QSS пункта навигации (строится после apply_theme)."""
    hover_bg = "rgba(255, 255, 255, 0.06)" if t.CURRENT_THEME == "dark" else "rgba(9, 17, 33, 0.05)"
    return f"""
QPushButton {{
    background: transparent; border: none; border-radius: 9px;
    padding: 0 12px; text-align: left; color: {t.TEXT_SECONDARY};
    font-size: {t.BODY_PT}pt; font-weight: 500;
}}
QPushButton:hover {{ background: {hover_bg}; padding: 0 12px; color: {t.TEXT}; }}
QPushButton:checked {{ background: transparent; color: {t.BLUE}; font-weight: 600; }}
"""


class _FooterBadge(QLabel):
    """Мини-бейдж футера: тонированная капсула состояния связи."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self.set_tone(BadgeTone.MUTED)

    def set_tone(self, tone: BadgeTone) -> None:
        """Перекрасить бейдж по тону состояния."""
        color = t.tone_color(tone)
        self.setText(self._label)
        self.setStyleSheet(
            f"QLabel {{ background: {t.tint(color, 0.12)}; color: {color};"
            f" border-radius: {t.RADIUS_CHIP}px; padding: 2px 8px;"
            f" font-size: {t.CAPTION_PT - 1}pt; font-weight: 600; }}"
        )


class Sidebar(QFrame):
    """Навигация как в нативных macOS-приложениях: стекло + скользящая капсула."""

    navigated = Signal(str)

    def __init__(self, version_line: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(t.SIDEBAR_WIDTH)
        self._ai_tone = BadgeTone.MUTED
        self._link_tones = (BadgeTone.MUTED, BadgeTone.MUTED, BadgeTone.MUTED)
        self._apply_frame_qss()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.SPACE_M, t.SPACE_L, t.SPACE_M, t.SPACE_M)
        layout.setSpacing(t.SPACE_XS)

        layout.addWidget(self._header())
        layout.addWidget(self._status_pill())
        layout.addSpacing(t.SPACE_L)

        # Хост навигации: капсула создаётся ПЕРВОЙ (рисуется под кнопками).
        self._nav_host = QWidget(self)
        nav_layout = QVBoxLayout(self._nav_host)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(t.SPACE_XS)
        self._capsule = QFrame(self._nav_host)
        self._apply_capsule_qss()
        self._capsule.hide()
        self._capsule_animation: QVariantAnimation | None = None

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for page_id, glyph, label in NAV_ITEMS:
            button = QPushButton(f"{glyph}  {label}", self._nav_host)
            button.setCheckable(True)
            button.setFixedHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_item_qss())
            button.clicked.connect(lambda _=False, pid=page_id: self.navigated.emit(pid))
            self._group.addButton(button)
            self._buttons[page_id] = button
            nav_layout.addWidget(button)
        layout.addWidget(self._nav_host)

        layout.addStretch(1)
        self._footer_widget = self._footer(version_line)
        layout.addWidget(self._footer_widget)

        self._active_id = ""
        self.select("dashboard")

    # ── Публичный контракт ────────────────────────────────────────────────────

    def select(self, page_id: str) -> None:
        """Отметить активный раздел (без эмита — навигацию решает окно).

        Капсула плавно скользит от прежнего пункта к новому.
        """
        button = self._buttons.get(page_id)
        if button is None:
            return
        button.setChecked(True)
        animate = bool(self._active_id) and self._active_id != page_id
        self._active_id = page_id
        self._move_capsule(button, animate=animate)

    def set_ai_tone(self, tone: BadgeTone) -> None:
        """Обновить статус-пилюлю приложения (🟢 Online / AI ACTIVE)."""
        self._ai_tone = tone
        self._pill_indicator.set_tone(tone)
        self._pill_label.setText(_PILL_TEXT.get(tone, "Ожидание"))
        color = t.tone_color(tone)
        self._pill.setStyleSheet(
            f"QFrame#StatusPill {{ background: {t.tint(color, 0.10)};"
            f" border: 1px solid {t.tint(color, 0.20)}; border-radius: 13px; }}"
        )

    def set_link_tones(self, telegram: BadgeTone, ati: BadgeTone, scheduler: BadgeTone) -> None:
        """Обновить бейджи связей в футере."""
        self._link_tones = (telegram, ati, scheduler)
        self._badge_telegram.set_tone(telegram)
        self._badge_ati.set_tone(ati)
        self._badge_scheduler.set_tone(scheduler)

    def page_ids(self) -> tuple[str, ...]:
        """Идентификаторы разделов (для окна и тестов)."""
        return tuple(page_id for page_id, _, _ in NAV_ITEMS)

    def refresh_theme(self) -> None:
        """Rebuild sidebar token-derived QSS after live theme switching."""
        self._apply_frame_qss()
        self._apply_capsule_qss()
        for button in self._buttons.values():
            button.setStyleSheet(_item_qss())
        self.set_ai_tone(self._ai_tone)
        self.set_link_tones(*self._link_tones)
        self._footer_widget.setStyleSheet(
            f"QFrame#SidebarFooter {{ background: {t.CARD};"
            f" border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_CONTROL}px; }}"
        )
        self._snap_capsule()

    def _apply_frame_qss(self) -> None:
        glow = (
            "rgba(255, 255, 255, 0.07)"
            if t.CURRENT_THEME == "dark"
            else "rgba(255, 255, 255, 0.85)"
        )
        self.setStyleSheet(
            f"""
QFrame#Sidebar {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {t.SIDEBAR_TOP}, stop: 1 {t.SIDEBAR_BOTTOM});
    border-right: 1px solid {t.BORDER};
    border-top: 1px solid {glow};
}}
"""
        )

    def _apply_capsule_qss(self) -> None:
        self._capsule.setStyleSheet(
            f"QFrame {{ background: {t.tint(t.BLUE, 0.14)};"
            f" border: 1px solid {t.tint(t.BLUE, 0.22)}; border-radius: 9px; }}"
        )

    # ── Капсула активного раздела ─────────────────────────────────────────────

    def _move_capsule(self, button: QPushButton, *, animate: bool) -> None:
        target = button.geometry()
        if target.width() <= 0:  # layout ещё не рассчитан — доснимем в showEvent
            return
        self._capsule.show()
        previous = self._capsule_animation
        if previous is not None and shiboken6.isValid(previous):
            previous.stop()
        if not animate:
            self._capsule.setGeometry(target)
            return
        animation = QVariantAnimation(self._capsule)
        animation.setDuration(t.DURATION_BASE)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(self._capsule.geometry())
        animation.setEndValue(target)
        animation.valueChanged.connect(self._on_capsule_frame)
        self._capsule_animation = animation
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_capsule_frame(self, value: object) -> None:
        if isinstance(value, QRect) and shiboken6.isValid(self._capsule):
            self._capsule.setGeometry(value)

    def _snap_capsule(self) -> None:
        """Прижать капсулу к активной кнопке без анимации (layout изменился)."""
        button = self._buttons.get(self._active_id)
        if button is not None:
            self._move_capsule(button, animate=False)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt API)
        """При первом показе геометрия кнопок уже рассчитана."""
        super().showEvent(event)
        self._snap_capsule()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API)
        """Капсула следует за пунктом при изменении размеров."""
        super().resizeEvent(event)
        self._snap_capsule()

    # ── Секции ────────────────────────────────────────────────────────────────

    def _header(self) -> QWidget:
        header = QWidget(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(t.SPACE_S, 0, t.SPACE_XS, 0)
        layout.setSpacing(t.SPACE_S)
        title = QLabel("LogistAI", header)
        title.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 700;"
            f" letter-spacing: 0.2px; background: transparent; }}"
        )
        layout.addWidget(title)
        layout.addStretch(1)
        return header

    def _status_pill(self) -> QWidget:
        self._pill = QFrame(self)
        self._pill.setObjectName("StatusPill")
        layout = QHBoxLayout(self._pill)
        layout.setContentsMargins(t.SPACE_S, 3, t.SPACE_M, 3)
        layout.setSpacing(2)
        self._pill_indicator = StatusIndicator(BadgeTone.MUTED, self._pill)
        self._pill_indicator.setToolTip("AI-диспетчер")
        layout.addWidget(self._pill_indicator)
        self._pill_label = QLabel(_PILL_TEXT[BadgeTone.MUTED], self._pill)
        self._pill_label.setStyleSheet(
            f"QLabel {{ font-size: {t.CAPTION_PT}pt; font-weight: 600; background: transparent; }}"
        )
        layout.addWidget(self._pill_label)
        layout.addStretch(1)
        self.set_ai_tone(BadgeTone.MUTED)
        return self._pill

    def _footer(self, version_line: str) -> QWidget:
        footer = QFrame(self)
        footer.setObjectName("SidebarFooter")
        footer.setStyleSheet(
            f"QFrame#SidebarFooter {{ background: {t.CARD};"
            f" border: 1px solid {t.BORDER}; border-radius: {t.RADIUS_CONTROL}px; }}"
        )
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(t.SPACE_M, t.SPACE_S, t.SPACE_M, t.SPACE_S)
        layout.setSpacing(t.SPACE_S)

        version = QLabel(version_line, footer)
        version.setWordWrap(True)  # длинная строка версии не режется капсулой
        version.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT}pt;"
            f" background: transparent; }}"
        )
        layout.addWidget(version)

        badges_host = QWidget(footer)
        badges = FlowLayout(badges_host, h_spacing=t.SPACE_XS, v_spacing=t.SPACE_XS)
        self._badge_telegram = _FooterBadge("Telegram", badges_host)
        self._badge_ati = _FooterBadge("ATI", badges_host)
        self._badge_scheduler = _FooterBadge("Планировщик", badges_host)
        for badge in (self._badge_telegram, self._badge_ati, self._badge_scheduler):
            badges.addWidget(badge)
        layout.addWidget(badges_host)
        return footer
