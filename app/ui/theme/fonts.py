"""Runtime-safe font selection for Qt.

Qt on macOS can spend time resolving aliases and print warnings when a QSS font
family is not actually installed. This module builds the font stack from the
families reported by QFontDatabase and falls back to QApplication/system fonts.
"""

from __future__ import annotations

import platform

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication


def resolve_font_stack() -> str:
    """Return a QSS font-family list with only available concrete families."""
    available = set(QFontDatabase.families())
    candidates = _macos_candidates() if platform.system() == "Darwin" else _linux_candidates()
    resolved: list[str] = []
    for family in candidates:
        if family in available and family not in resolved:
            resolved.append(family)

    app_font = QApplication.font().family()
    if app_font and app_font not in resolved:
        resolved.append(app_font)
    if not resolved:
        resolved.append("sans-serif")
    return ", ".join(_quote(family) for family in resolved)


def _macos_candidates() -> tuple[str, ...]:
    return (
        ".AppleSystemUIFont",
        "SF Pro Text",
        "SF Pro Display",
        "Helvetica Neue",
        "Arial",
    )


def _linux_candidates() -> tuple[str, ...]:
    return (
        "Inter",
        "Arial",
        "Noto Sans",
        "DejaVu Sans",
        "Sans Serif",
    )


def _quote(family: str) -> str:
    return family if family == "sans-serif" else f'"{family}"'
