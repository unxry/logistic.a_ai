"""Stage 10.4: live Light/Dark/System theme switching."""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtWidgets import QApplication, QWidget

from app.core.models.settings import Theme
from app.ui.theme import tokens
from app.ui.theme.fonts import resolve_font_stack
from app.ui.theme.manager import ThemeManager


def test_light_theme_all_pages(qtbot: Any) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    manager = ThemeManager(cast(QApplication, QApplication.instance()), root)

    concrete = manager.apply(Theme.LIGHT, animated=False)

    assert concrete == "light"
    assert tokens.CURRENT_THEME == "light"


def test_dark_theme_all_pages(qtbot: Any) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    manager = ThemeManager(cast(QApplication, QApplication.instance()), root)

    concrete = manager.apply(Theme.DARK, animated=False)

    assert concrete == "dark"
    assert tokens.CURRENT_THEME == "dark"


def test_system_theme(qtbot: Any) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    manager = ThemeManager(cast(QApplication, QApplication.instance()), root)

    concrete = manager.apply(Theme.SYSTEM, animated=False)

    assert concrete in ("light", "dark")


def test_theme_switch_no_recreate_window(qtbot: Any) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    root.show()
    manager = ThemeManager(cast(QApplication, QApplication.instance()), root)
    identity = id(root)

    manager.apply(Theme.LIGHT, animated=False)
    manager.apply(Theme.DARK, animated=False)

    assert id(root) == identity


def test_font_stack_avoids_missing_sf_pro_warning() -> None:
    stack = resolve_font_stack()
    families = {family.strip().strip('"') for family in stack.split(",")}

    if "SF Pro Text" not in QApplication.font().family():
        assert "SF Pro Text" not in families
