"""Смоук пакетной структуры: всё импортируется, версия из единого источника."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path

import app

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_version_single_source() -> None:
    """Версия приложения читается из файла VERSION — единственного источника."""
    from app.infrastructure.system.build_info import load_build_info

    expected = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert expected, "файл VERSION не должен быть пустым"
    assert load_build_info().version == expected


def test_all_packages_importable() -> None:
    """Каждый модуль проекта импортируется без ошибок.

    UI-модули требуют PySide6 и пропускаются, если Qt недоступен
    (app.bootstrap импортирует Qt лениво, поэтому проверяется всегда).
    """
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        qt_dependent = "ui" in info.name.split(".")
        if qt_dependent and not QT_AVAILABLE:
            continue
        importlib.import_module(info.name)
