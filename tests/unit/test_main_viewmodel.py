"""Тесты MainViewModel — без Qt (ViewModel не зависит от виджетов)."""

from __future__ import annotations

from app.core.models.build_info import BuildInfo, BuildMode
from app.ui.viewmodels.main_viewmodel import MainViewModel


def _view_model() -> MainViewModel:
    info = BuildInfo(version="9.9.9-test", build_date=None, git_commit=None, mode=BuildMode.DEBUG)
    return MainViewModel(info)


def test_window_title() -> None:
    assert _view_model().window_title == "LogistAI · LIVE"


def test_status_line_contains_version_and_mode() -> None:
    line = _view_model().status_line
    assert "9.9.9-test" in line
    assert "debug" in line
    assert "LIVE" in line


def test_mode_label_can_show_demo() -> None:
    info = BuildInfo(version="9.9.9-test", build_date=None, git_commit=None, mode=BuildMode.DEBUG)
    vm = MainViewModel(info, mode_label="DEMO")

    assert vm.window_title == "LogistAI · DEMO"
    assert "DEMO" in vm.status_line
