"""Охрана дизайн-системы: docs/design-system.md и tokens.py не расходятся."""

from __future__ import annotations

from pathlib import Path

from app.ui.theme import tokens
from app.ui.viewmodels import BadgeTone

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_palette_matches_design_doc() -> None:
    doc = (PROJECT_ROOT / "docs" / "design-system.md").read_text(encoding="utf-8")
    for value in (
        tokens.BG,
        tokens.BLUE,
        tokens.GREEN,
        tokens.ORANGE,
        tokens.RED,
        tokens.CARD,
        tokens.TEXT,
        tokens.TEXT_SECONDARY,
    ):
        assert value in doc, f"токен {value} не описан в design-system.md"


def test_spec_colors_are_exact() -> None:
    """Цвета состояний — ровно из ТЗ."""
    assert tokens.BG == "#F5F5F7"
    assert tokens.GREEN == "#30D158"
    assert tokens.ORANGE == "#FF9F0A"
    assert tokens.RED == "#FF453A"
    assert tokens.BLUE == "#0A84FF"


def test_tone_mapping_and_tint() -> None:
    assert tokens.tone_color(BadgeTone.OK) == tokens.GREEN
    assert tokens.tone_color(BadgeTone.ERROR) == tokens.RED
    assert tokens.tint(tokens.BLUE) == "rgba(10, 132, 255, 0.12)"


def test_motion_durations_within_limits() -> None:
    """Дизайн-правило: никакого движения дольше 400 мс (кроме пульса/счёта)."""
    assert tokens.DURATION_FAST <= tokens.DURATION_BASE <= tokens.DURATION_ENTER <= 400
    assert tokens.SHADOW_RESTING.blur < tokens.SHADOW_LIFTED.blur
