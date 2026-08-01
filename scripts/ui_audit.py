"""Automated UI audit runner for demo mode.

The runner opens the PySide UI, navigates every page, switches Light/Dark
themes, captures screenshots, records runtime warnings/errors, and exits
without starting live polling or Telegram.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import redirect_stderr
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, TextIO

import shiboken6
from PySide6.QtCore import QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.bootstrap import build_container
from app.core.models.settings import Theme
from app.ui.main_window import MainWindow
from app.ui.theme import tokens
from app.ui.theme.fonts import resolve_font_stack
from app.ui.theme.manager import ThemeManager
from app.ui.viewmodels import MOCK_POTENTIAL_PROFIT, mock_best_matches
from app.ui.viewmodels.main_viewmodel import MainViewModel

ARTIFACTS = Path("artifacts/ui-audit")
PAGES = (
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
THEMES = (Theme.LIGHT, Theme.DARK)


class _ContainerLike(Protocol):
    dashboard_viewmodel: object


@dataclass(frozen=True, slots=True)
class UiAuditReport:
    pages: tuple[str, ...]
    themes: tuple[str, ...]
    screenshots: int
    runtime_errors: int
    qt_warnings: int
    invalid_qobjects: int
    unhandled_asyncio_tasks: int


class _RuntimeLog:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self.messages: list[str] = []

    def write(self, value: str) -> int:
        self.messages.append(value)
        return self._stream.write(value)

    def flush(self) -> None:
        self._stream.flush()


class _QtLogHandler(logging.Handler):
    def __init__(self, sink: _RuntimeLog) -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.write(self.format(record) + "\n")


async def _refresh(window: MainWindow, container: _ContainerLike) -> None:
    dashboard = container.dashboard_viewmodel
    await dashboard.refresh()
    dashboard.set_recommendation_cards(mock_best_matches(), potential_profit=MOCK_POTENTIAL_PROFIT)
    window.resize(1280, 820)


def _process_events(wait_ms: int = 0) -> None:
    if wait_ms > 0:
        QTest.qWait(wait_ms)
    for _ in range(4):
        QApplication.processEvents()


def _capture_current(window: MainWindow, theme: Theme, name: str) -> Path:
    directory = ARTIFACTS / theme.value
    directory.mkdir(parents=True, exist_ok=True)
    _process_events()
    path = directory / f"{name}.png"
    window.grab().save(str(path))
    return path


def _capture_page(window: MainWindow, theme: Theme, page_id: str) -> Path:
    window.show_page(page_id)
    window.resize(1100, 720)
    _process_events(tokens.DURATION_BASE + 80)
    window.resize(1440, 900)
    _process_events(tokens.DURATION_BASE + 80)
    return _capture_current(window, theme, page_id)


def _exercise_hover(widget: QWidget) -> None:
    for child in widget.findChildren(QWidget)[:80]:
        if not shiboken6.isValid(child) or not child.isVisible():
            continue
        QTest.mouseMove(child, child.rect().center())
        child.update()
        QTest.qWait(1)
    _process_events()


def _open_modal_and_palette(window: MainWindow, theme: Theme, screenshots: list[Path]) -> None:
    window.open_palette()
    _process_events(tokens.DURATION_BASE + 80)
    screenshots.append(_capture_current(window, theme, "command_palette"))
    window.command_palette.close_overlay()
    _process_events(40)

    window._explain_cargo(mock_best_matches()[0])
    _process_events(tokens.DURATION_ENTER + 80)
    screenshots.append(_capture_current(window, theme, "explanation_sheet"))
    window.modal.close_overlay()
    _process_events(40)


def _run_qt_audit(runtime_log: _RuntimeLog) -> UiAuditReport:
    app = QApplication(["ui-audit", "--demo"])
    app.setApplicationName("LogistAI UI Audit")
    app.setQuitOnLastWindowClosed(False)
    tokens.FONT_STACK = resolve_font_stack()
    tokens.apply_theme("light")
    container = build_container(demo_dashboard=True)
    screenshots: list[Path] = []
    handler = _QtLogHandler(runtime_log)
    logging.getLogger().addHandler(handler)
    try:
        window = MainWindow(
            MainViewModel(container.build_info, mode_label="DEMO"),
            container.dashboard_viewmodel,
            container.event_bus,
            command_dispatcher=container.command_bus,
            current_settings=container.settings_service.current,
            demo=True,
        )
        manager = ThemeManager(app, window)
        window.set_theme_manager(manager)
        window.resize(QSize(1280, 820))
        window.show()
        asyncio.run(_refresh(window, container))
        _process_events(tokens.DURATION_ENTER + 80)

        for theme in THEMES:
            manager.apply(theme, animated=False)
            _process_events(tokens.DURATION_BASE + 80)
            for page_id in PAGES:
                screenshots.append(_capture_page(window, theme, page_id))
                _exercise_hover(window)
            _open_modal_and_palette(window, theme, screenshots)

        window.close()
        _process_events()
        container.database.close()
    finally:
        logging.getLogger().removeHandler(handler)
        app.quit()

    combined = "".join(runtime_log.messages)
    return UiAuditReport(
        pages=PAGES,
        themes=tuple(theme.value for theme in THEMES),
        screenshots=len(screenshots),
        runtime_errors=combined.count("Traceback"),
        qt_warnings=combined.count("Qt"),
        invalid_qobjects=combined.count("Internal C++ object"),
        unhandled_asyncio_tasks=combined.count("Task exception was never retrieved"),
    )


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    runtime_log = _RuntimeLog(sys.stderr)
    with (ARTIFACTS / "runtime.log").open("w", encoding="utf-8") as log_file:
        with redirect_stderr(runtime_log):
            report = _run_qt_audit(runtime_log)
        log_file.write("".join(runtime_log.messages))

    (ARTIFACTS / "report.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"UI audit screenshots: {report.screenshots}")
    print(f"Runtime errors: {report.runtime_errors}")
    print(f"Qt warnings: {report.qt_warnings}")
    print(f"Invalid QObjects: {report.invalid_qobjects}")
    print(f"Unhandled asyncio tasks: {report.unhandled_asyncio_tasks}")
    return (
        0
        if report.runtime_errors == 0
        and report.invalid_qobjects == 0
        and report.unhandled_asyncio_tasks == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
