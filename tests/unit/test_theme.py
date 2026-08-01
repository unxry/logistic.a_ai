"""Stage 9.8: двойная палитра Light/Dark и переключение ``apply_theme``."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from app.ui.theme import tokens

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dark_palette_is_full_palette_not_inversion() -> None:
    """Каждое поле тёмной палитры задано отдельно (не «инверсия» светлой)."""
    for field in fields(tokens.ThemePalette):
        light_value = getattr(tokens.LIGHT, field.name)
        dark_value = getattr(tokens.DARK, field.name)
        assert light_value != dark_value, f"{field.name} совпадает в Light и Dark"


def test_dark_background_is_graphite_not_black() -> None:
    """Требование 9.8: фон очень тёмный графит, НЕ чёрный; карточки светлее."""
    assert tokens.DARK.bg.lower() not in ("#000000", "#000")
    assert tokens.DARK.card_solid != tokens.DARK.bg
    assert tokens.DARK.text == "#F5F5F7"  # системный светлый текст macOS


def test_apply_theme_switches_and_restores() -> None:
    try:
        tokens.apply_theme("dark")
        assert tokens.CURRENT_THEME == "dark"
        assert tokens.DARK.bg == tokens.BG
        assert tokens.DARK.text == tokens.TEXT
        assert tokens.DARK.card_hover == tokens.CARD_HOVER
        assert tokens.DARK.sidebar_top == tokens.SIDEBAR_TOP
        assert tokens.DARK.skeleton_base_rgba == tokens.SKELETON_BASE_RGBA
        # Акценты Apple общие для обеих тем (без «кислотности»).
        assert tokens.BLUE == "#0A84FF"
        assert tokens.GREEN == "#30D158"
        # Тени в темноте глубже.
        assert tokens.SHADOW_RESTING.rgba[3] > 26
    finally:
        tokens.apply_theme("light")
    assert tokens.CURRENT_THEME == "light"
    assert tokens.LIGHT.bg == tokens.BG
    assert tokens.SHADOW_RESTING.rgba == (16, 24, 40, 26)


def test_apply_theme_unknown_value_falls_back_to_light() -> None:
    try:
        tokens.apply_theme("System")
        assert tokens.CURRENT_THEME == "light"
        assert tokens.LIGHT.bg == tokens.BG
    finally:
        tokens.apply_theme("light")


def test_three_shadow_levels_are_ordered() -> None:
    """REST / HOVER(LIFTED) / ACTIVE: нажатие прижимает, hover поднимает."""
    assert tokens.SHADOW_ACTIVE.blur < tokens.SHADOW_RESTING.blur < tokens.SHADOW_LIFTED.blur
    assert (
        tokens.SHADOW_ACTIVE.y_offset
        < tokens.SHADOW_RESTING.y_offset
        < tokens.SHADOW_LIFTED.y_offset
    )


def test_dark_palette_matches_design_doc() -> None:
    doc = (PROJECT_ROOT / "docs" / "design-system.md").read_text(encoding="utf-8")
    for value in (
        tokens.DARK.bg,
        tokens.DARK.card,
        tokens.DARK.card_solid,
        tokens.DARK.text,
        tokens.DARK.text_secondary,
    ):
        assert value in doc, f"токен тёмной темы {value} не описан в design-system.md"
