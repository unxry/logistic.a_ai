"""Глобальный QSS приложения, собранный из токенов дизайн-системы.

Stage 9.8: строится ПОСЛЕ ``tokens.apply_theme`` — обе темы (Light/Dark)
получают свои поверхности из одного шаблона. Скроллбары — «невидимки»
в духе macOS: прозрачны в покое, проявляются при прокрутке (динамическое
свойство ``revealed`` ставит ``motion.reveal_scrollbar_on_scroll``).
"""

from __future__ import annotations

from app.ui.theme import tokens as t


def _scroll_handle(alpha: float) -> str:
    """Ручка скроллбара: тёмная на светлой теме, светлая на тёмной."""
    if t.CURRENT_THEME == "dark":
        return f"rgba(255, 255, 255, {min(1.0, alpha + 0.06):.2f})"
    return f"rgba(9, 17, 33, {alpha:.2f})"


def build_global_qss() -> str:
    """Стиль приложения: фон, шрифт, скроллбары, поля ввода, тултипы."""
    return f"""
QWidget {{
    font-family: {t.FONT_STACK};
    font-size: {t.BODY_PT}pt;
    color: {t.TEXT};
}}
QMainWindow, QWidget#AppRoot {{
    background-color: {t.BG};
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}

QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: transparent; border-radius: 3px; min-height: 36px;
}}
QScrollBar[revealed="true"]::handle:vertical {{ background: {_scroll_handle(0.16)}; }}
QScrollBar::handle:vertical:hover {{ background: {_scroll_handle(0.30)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: transparent; border-radius: 3px; min-width: 36px;
}}
QScrollBar[revealed="true"]::handle:horizontal {{ background: {_scroll_handle(0.16)}; }}
QScrollBar::handle:horizontal:hover {{ background: {_scroll_handle(0.30)}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QLineEdit {{
    background: {t.CARD_SOLID};
    border: 1px solid {t.BORDER};
    border-radius: {t.RADIUS_CONTROL}px;
    padding: 8px 12px;
    selection-background-color: {t.tint(t.BLUE, 0.25)};
}}
QLineEdit:focus {{ border: 1px solid {t.BLUE}; padding: 8px 12px; }}

QToolTip {{
    background: {t.CARD_SOLID};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    padding: 6px 10px;
}}

QStatusBar {{
    background: transparent;
    color: {t.TEXT_SECONDARY};
}}
QStatusBar::item {{ border: none; }}
"""
