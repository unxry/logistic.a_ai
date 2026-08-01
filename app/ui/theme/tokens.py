"""Дизайн-токены LogistAI (источник: docs/design-system.md, охраняется тестом).

Все виджеты берут цвета/размеры/тени/длительности ОТСЮДА — прямых hex-значений
в коде компонентов нет. Stage 9.8: две ПОЛНОЦЕННЫЕ палитры (Light и Dark —
не инверсия, а отдельные значения уровня macOS Sonoma); ``apply_theme``
вызывается composition root'ом ДО сборки окна.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ui.viewmodels import BadgeTone


@dataclass(frozen=True, slots=True)
class ThemePalette:
    """Палитра темы: поверхности и текст (акценты общие для обеих тем)."""

    bg: str
    card: str
    card_hover: str
    card_solid: str
    sidebar_top: str
    sidebar_bottom: str
    border: str
    text: str
    text_secondary: str
    text_tertiary: str
    skeleton_base_rgba: tuple[int, int, int, int]
    shadow_rgb: tuple[int, int, int]


LIGHT = ThemePalette(
    bg="#F5F5F7",
    card="rgba(255, 255, 255, 0.72)",
    card_hover="rgba(255, 255, 255, 0.92)",
    card_solid="#FFFFFF",
    sidebar_top="rgba(250, 250, 252, 0.92)",
    sidebar_bottom="rgba(242, 242, 246, 0.80)",
    border="rgba(9, 17, 33, 0.07)",
    text="#1D1D1F",
    text_secondary="#6E6E73",
    text_tertiary="#AEAEB2",
    skeleton_base_rgba=(9, 17, 33, 16),
    shadow_rgb=(16, 24, 40),
)

#: Тёмный графит Sonoma: фон НЕ чёрный, карточки заметно светлее фона.
DARK = ThemePalette(
    bg="#161618",
    card="rgba(44, 44, 46, 0.66)",
    card_hover="rgba(58, 58, 60, 0.78)",
    card_solid="#232326",
    sidebar_top="rgba(32, 32, 34, 0.94)",
    sidebar_bottom="rgba(24, 24, 26, 0.86)",
    border="rgba(255, 255, 255, 0.09)",
    text="#F5F5F7",
    text_secondary="#A1A1A6",
    text_tertiary="#6E6E73",
    skeleton_base_rgba=(255, 255, 255, 18),
    shadow_rgb=(0, 0, 0),
)

# ── Цвет (значения активной темы; по умолчанию — Light) ─────────────────────

BG = LIGHT.bg
CARD = LIGHT.card
CARD_HOVER = LIGHT.card_hover
CARD_SOLID = LIGHT.card_solid
SIDEBAR = LIGHT.sidebar_top
SIDEBAR_TOP = LIGHT.sidebar_top
SIDEBAR_BOTTOM = LIGHT.sidebar_bottom
BORDER = LIGHT.border

TEXT = LIGHT.text
TEXT_SECONDARY = LIGHT.text_secondary
TEXT_TERTIARY = LIGHT.text_tertiary

SKELETON_BASE_RGBA = LIGHT.skeleton_base_rgba

BLUE = "#0A84FF"
GREEN = "#30D158"
ORANGE = "#FF9F0A"
RED = "#FF453A"
MUTED = "#8E8E93"

CURRENT_THEME = "light"

_TONE_COLOR: dict[BadgeTone, str] = {
    BadgeTone.OK: GREEN,
    BadgeTone.WARNING: ORANGE,
    BadgeTone.ERROR: RED,
    BadgeTone.MUTED: MUTED,
}

_RGB: dict[str, tuple[int, int, int]] = {
    BLUE: (10, 132, 255),
    GREEN: (48, 209, 88),
    ORANGE: (255, 159, 10),
    RED: (255, 69, 58),
    MUTED: (142, 142, 147),
}


def tone_color(tone: BadgeTone) -> str:
    """Цвет состояния (semantic-маппинг дизайн-системы)."""
    return _TONE_COLOR[tone]


def tint(color: str, alpha: float = 0.12) -> str:
    """Тонировка «цвет @ 12%» для фонов бейджей и чипов."""
    r, g, b = _RGB.get(color, (110, 110, 115))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


# ── Типографика ───────────────────────────────────────────────────────────────

FONT_STACK = (
    '".AppleSystemUIFont", "SF Pro Text", "SF Pro Display", "Helvetica Neue", '
    '"Inter", "Segoe UI", "Noto Sans", sans-serif'
)

DISPLAY_PT = 30
TITLE_PT = 21
HEADLINE_PT = 15
BODY_PT = 13
CAPTION_PT = 11


# ── Сетка, радиусы, размеры ───────────────────────────────────────────────────

SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16
SPACE_XL = 20
SPACE_XXL = 24
SPACE_PAGE = 24

RADIUS_CHIP = 8
RADIUS_CONTROL = 10
RADIUS_CARD = 16
RADIUS_HERO = 20

SIDEBAR_WIDTH = 224
BUTTON_HEIGHT = 36
BUTTON_HEIGHT_COMPACT = 30

WINDOW_MIN_W = 1080
WINDOW_MIN_H = 700
WINDOW_DEFAULT_W = 1280
WINDOW_DEFAULT_H = 800


# ── Тени ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ShadowSpec:
    """Параметры QGraphicsDropShadowEffect."""

    blur: int
    y_offset: int
    rgba: tuple[int, int, int, int]


SHADOW_RESTING = ShadowSpec(blur=28, y_offset=8, rgba=(16, 24, 40, 26))
SHADOW_LIFTED = ShadowSpec(blur=44, y_offset=16, rgba=(16, 24, 40, 46))
SHADOW_ACTIVE = ShadowSpec(blur=18, y_offset=4, rgba=(16, 24, 40, 36))  # нажатие
SHADOW_GLOW_BLUE = ShadowSpec(blur=36, y_offset=0, rgba=(10, 132, 255, 90))


def apply_theme(theme: str) -> None:
    """Переключить активную палитру («light»/«dark») ДО сборки виджетов.

    Мутирует модульные значения: QSS, собираемый в __init__ виджетов, и
    QColor'ы в paintEvent получают тему автоматически. Живое переключение
    без пересборки окна — вместе с формами настроек (Stage 9.1).
    """
    global BG, CARD, CARD_HOVER, CARD_SOLID, SIDEBAR, SIDEBAR_TOP, SIDEBAR_BOTTOM
    global BORDER, TEXT, TEXT_SECONDARY, TEXT_TERTIARY, SKELETON_BASE_RGBA
    global SHADOW_RESTING, SHADOW_LIFTED, SHADOW_ACTIVE, CURRENT_THEME
    palette = DARK if theme.strip().lower() == "dark" else LIGHT
    CURRENT_THEME = "dark" if palette is DARK else "light"
    BG = palette.bg
    CARD = palette.card
    CARD_HOVER = palette.card_hover
    CARD_SOLID = palette.card_solid
    SIDEBAR = palette.sidebar_top
    SIDEBAR_TOP = palette.sidebar_top
    SIDEBAR_BOTTOM = palette.sidebar_bottom
    BORDER = palette.border
    TEXT = palette.text
    TEXT_SECONDARY = palette.text_secondary
    TEXT_TERTIARY = palette.text_tertiary
    SKELETON_BASE_RGBA = palette.skeleton_base_rgba
    r, g, b = palette.shadow_rgb
    depth = 1.0 if palette is LIGHT else 1.8  # в темноте тени глубже
    SHADOW_RESTING = ShadowSpec(blur=28, y_offset=8, rgba=(r, g, b, min(255, int(26 * depth))))
    SHADOW_LIFTED = ShadowSpec(blur=44, y_offset=16, rgba=(r, g, b, min(255, int(46 * depth))))
    SHADOW_ACTIVE = ShadowSpec(blur=18, y_offset=4, rgba=(r, g, b, min(255, int(36 * depth))))


# ── Движение (мс) ─────────────────────────────────────────────────────────────

DURATION_FAST = 140
DURATION_BASE = 220
DURATION_ENTER = 320
DURATION_COUNT = 650
DURATION_PULSE = 1600
TOAST_LIFETIME_MS = 4200
