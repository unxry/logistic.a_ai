"""Смоук главного окна Stage 9: shell, навигация, палитра, hero, статусы."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

pytest.importorskip("PySide6", reason="PySide6 не установлен в этом окружении")
pytest.importorskip("pytestqt", reason="pytest-qt не установлен в этом окружении")

from PySide6.QtWidgets import QApplication

from app.buses import EventBus
from app.core.commands import Command, SaveSettings
from app.core.models.build_info import BuildInfo, BuildMode
from app.core.models.settings import AppSettings, Theme
from app.ui.main_window import MainWindow
from app.ui.theme.manager import ThemeManager
from app.ui.viewmodels import (
    MOCK_NOW,
    MOCK_POTENTIAL_PROFIT,
    BadgeTone,
    DashboardViewModel,
    MainViewModel,
    MockDashboardDataProvider,
    mock_best_matches,
)


class _Dispatcher:
    def __init__(self) -> None:
        self.saved: list[AppSettings] = []

    async def dispatch[R](self, command: Command[R]) -> R:
        if isinstance(command, SaveSettings):
            self.saved.append(command.settings)
        return cast(R, None)


def _window(
    qtbot: Any,
    *,
    dispatcher: _Dispatcher | None = None,
) -> tuple[MainWindow, DashboardViewModel]:
    bus = EventBus()
    dashboard = DashboardViewModel(
        provider=MockDashboardDataProvider(), events=bus, clock=lambda: MOCK_NOW
    )
    info = BuildInfo(version="0.0.0-test", build_date=None, git_commit=None, mode=BuildMode.DEBUG)
    window = MainWindow(
        MainViewModel(info),
        dashboard,
        bus,
        command_dispatcher=dispatcher,
        current_settings=AppSettings(),
        demo=True,
    )
    app = cast(QApplication, QApplication.instance())
    window.set_theme_manager(ThemeManager(app, window))
    qtbot.addWidget(window)
    window.show()  # оверлеи (палитра, тосты) видимы только у показанного окна
    return window, dashboard


def test_window_shell_builds(qtbot: Any) -> None:
    window, _ = _window(qtbot)
    assert window.windowTitle() == "LogistAI · LIVE"
    assert window.minimumWidth() >= 1080
    assert window.sidebar.page_ids() == (
        "dashboard",
        "cargo",
        "favorites",
        "vehicle",
        "search",
        "analytics",
        "notifications",
        "sources",
        "settings",
    )
    assert window.current_page_id() == "dashboard"


def test_navigation_switches_pages(qtbot: Any) -> None:
    window, _ = _window(qtbot)
    for page_id in window.sidebar.page_ids():
        window.show_page(page_id)
        assert window.current_page_id() == page_id


def test_refresh_fills_status_bar_and_pages(qtbot: Any) -> None:
    window, dashboard = _window(qtbot)
    asyncio.run(dashboard.refresh())

    assert window._status_telegram.text() == "Подключён"
    # ozon FAILED в мок-данных → приложение «работает с проблемами»
    assert window._status_app.text() == "Работает с проблемами"
    page = window.dashboard_page
    assert page.metric_found is not None
    assert page.timeline.rows_count() > 0
    assert window.current_page_id() == "dashboard"


def test_recommendations_fill_hero_and_cards(qtbot: Any) -> None:
    window, dashboard = _window(qtbot)
    asyncio.run(dashboard.refresh())
    dashboard.set_recommendation_cards(mock_best_matches(), potential_profit=MOCK_POTENTIAL_PROFIT)

    hero_card = window.dashboard_page.hero.current_card
    assert hero_card is not None and hero_card.cargo_id == "cargo-spb"
    assert window.dashboard_page.cargo_widgets_count() == 3
    assert window.dashboard_page.metric_profit._value.text() == "160 610 ₽"


def test_ignore_removes_best_cargo(qtbot: Any) -> None:
    window, dashboard = _window(qtbot)
    asyncio.run(dashboard.refresh())
    dashboard.set_recommendation_cards(mock_best_matches())

    window._ignore_cargo("cargo-spb")

    hero_card = window.dashboard_page.hero.current_card
    assert hero_card is not None and hero_card.cargo_id == "cargo-kazan"
    assert window.dashboard_page.cargo_widgets_count() == 2


def test_command_palette_navigates(qtbot: Any) -> None:
    window, _ = _window(qtbot)
    window.open_palette()
    assert window.command_palette.isVisible()

    window.command_palette._search.setText("аналит")
    commands = window.command_palette.visible_commands()
    assert commands and commands[0].id == "go-analytics"
    window.command_palette.run_selected()

    assert not window.command_palette.isVisible()
    assert window.current_page_id() == "analytics"


def test_demo_command_registered(qtbot: Any) -> None:
    from app.ui.widgets import Command

    bus = EventBus()
    dashboard = DashboardViewModel(provider=MockDashboardDataProvider(), events=bus)
    info = BuildInfo(version="0.0.0-test", build_date=None, git_commit=None, mode=BuildMode.DEBUG)
    marker: list[str] = []
    window = MainWindow(
        MainViewModel(info),
        dashboard,
        bus,
        extra_commands=(Command(id="demo", title="Демо", run=lambda: marker.append("hit")),),
    )
    qtbot.addWidget(window)
    window.show()
    window.open_palette()
    window.command_palette._search.setText("Демо")
    window.command_palette.run_selected()
    assert marker == ["hit"]


def test_source_error_shows_toast(qtbot: Any) -> None:
    window, dashboard = _window(qtbot)
    window.show()
    asyncio.run(dashboard.refresh())
    from app.ui.viewmodels import SourceStatusViewModel, StatusBadge

    failed = SourceStatusViewModel(
        id="ozon",
        name="Ozon Логистика",
        status=StatusBadge(tone=BadgeTone.ERROR, label="Недоступен"),
        last_sync="42 мин назад",
        cargo_count=87,
        errors="HTTP 503",
    )
    window._on_source_changed(failed)
    assert window.toasts.isVisible()


def test_all_buttons_smoke(qtbot: Any) -> None:
    dispatcher = _Dispatcher()
    window, _ = _window(qtbot, dispatcher=dispatcher)

    window._create_vehicle()
    qtbot.wait(20)
    window._duplicate_vehicle()
    qtbot.wait(20)
    window._edit_vehicle()
    qtbot.wait(20)
    window._delete_vehicle()
    qtbot.wait(20)
    window._change_theme(Theme.LIGHT)
    qtbot.wait(20)

    assert dispatcher.saved
    assert dispatcher.saved[-1].ui.theme is Theme.LIGHT


def test_theme_switch_no_recreate_window(qtbot: Any) -> None:
    window, _ = _window(qtbot)
    identity = id(window)

    window._change_theme(Theme.LIGHT)
    window._change_theme(Theme.DARK)
    qtbot.wait(60)

    assert id(window) == identity


def test_sidebar_rapid_hover(qtbot: Any) -> None:
    window, _ = _window(qtbot)

    for index in range(50):
        page_id = window.sidebar.page_ids()[index % len(window.sidebar.page_ids())]
        window.sidebar.select(page_id)

    assert window.sidebar._capsule_animation is not None
