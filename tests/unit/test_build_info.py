"""Тесты BuildInfo: единый источник версии, режимы сборки."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models.build_info import BuildInfo, BuildMode
from app.infrastructure.system.build_info import load_build_info

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_version_matches_version_file() -> None:
    expected = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert load_build_info().version == expected


def test_default_mode_is_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGISTAI_MODE", raising=False)
    info = load_build_info()
    assert info.mode is BuildMode.DEBUG
    assert info.is_debug


def test_release_mode_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGISTAI_MODE", "release")
    assert load_build_info().mode is BuildMode.RELEASE


def test_invalid_mode_falls_back_to_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGISTAI_MODE", "totally-wrong")
    assert load_build_info().mode is BuildMode.DEBUG


def test_display_contains_version_and_mode() -> None:
    info = BuildInfo(version="1.2.3", build_date=None, git_commit=None, mode=BuildMode.DEBUG)
    assert info.display() == "1.2.3 · debug"
