"""Stage 10.4: qasync-safe shutdown coordinator."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from PySide6.QtWidgets import QWidget

from app.core.commands import StopScheduler
from app.core.events import AppClosing, Event
from app.runtime import ShutdownCoordinator
from app.ui.theme import AnimationManager


class _Events:
    def __init__(self) -> None:
        self.published: list[Event] = []

    def publish(self, event: Event) -> None:
        self.published.append(event)


class _Commands:
    def __init__(self) -> None:
        self.commands: list[object] = []

    async def dispatch[R](self, command: object) -> R:
        self.commands.append(command)
        return cast(R, None)


class _Telegram:
    def __init__(self) -> None:
        self.stopped = 0

    async def stop(self) -> None:
        self.stopped += 1


class _Pipeline:
    def __init__(self) -> None:
        self.waited = 0

    async def wait_idle(self) -> None:
        self.waited += 1


class _Ati:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class _Database:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class _Menu:
    def __init__(self) -> None:
        self.detached = 0

    def detach(self) -> None:
        self.detached += 1


def _coordinator(**overrides: Any) -> tuple[ShutdownCoordinator, dict[str, Any]]:
    parts: dict[str, Any] = {
        "events": _Events(),
        "commands": _Commands(),
        "telegram": _Telegram(),
        "pipeline": _Pipeline(),
        "ati": _Ati(),
        "database": _Database(),
        "menu": _Menu(),
    }
    parts.update(overrides)
    coordinator = ShutdownCoordinator(
        event_bus=parts["events"],
        command_bus=parts["commands"],
        telegram_bot=parts["telegram"],
        recommendation_pipeline=parts["pipeline"],
        ati_client=parts["ati"],
        database=parts["database"],
        menu_bar=parts["menu"],
        timeout_seconds=2.0,
    )
    return coordinator, parts


async def test_shutdown_from_menu_bar_quit() -> None:
    shutdown, parts = _coordinator()

    await shutdown.shutdown_now("menu_bar")

    assert shutdown.finished.is_set()
    assert any(isinstance(event, AppClosing) for event in parts["events"].published)
    assert isinstance(parts["commands"].commands[0], StopScheduler)
    assert parts["telegram"].stopped == 1
    assert parts["pipeline"].waited == 1
    assert parts["ati"].closed == 1
    assert parts["database"].closed == 1
    assert parts["menu"].detached == 1


async def test_shutdown_from_window_close() -> None:
    shutdown, parts = _coordinator()

    await shutdown.shutdown_now("window_close")

    assert shutdown.finished.is_set()
    assert parts["database"].closed == 1


async def test_shutdown_from_cmd_q() -> None:
    shutdown, parts = _coordinator()

    await shutdown.shutdown_now("cmd_q")

    assert shutdown.finished.is_set()
    assert isinstance(parts["commands"].commands[0], StopScheduler)


async def test_shutdown_called_twice() -> None:
    shutdown, parts = _coordinator()

    await shutdown.shutdown_now("window")
    await shutdown.shutdown_now("cmd_q")

    assert parts["database"].closed == 1
    assert len(parts["commands"].commands) == 1


async def test_shutdown_with_running_scheduler_and_telegram_polling() -> None:
    shutdown, parts = _coordinator()

    await shutdown.shutdown_now("running")

    assert isinstance(parts["commands"].commands[0], StopScheduler)
    assert parts["telegram"].stopped == 1


async def test_shutdown_with_running_telegram_polling() -> None:
    shutdown, parts = _coordinator()

    await shutdown.shutdown_now("telegram_polling")

    assert parts["telegram"].stopped == 1


async def test_shutdown_with_pending_animation(qtbot: Any) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    AnimationManager.instance().animate_scale(widget, duration_ms=500)
    assert AnimationManager.instance()._animations.get(widget)
    shutdown, _ = _coordinator()

    await shutdown.shutdown_now("animation")

    assert not AnimationManager.instance()._animations.get(widget)


async def test_shutdown_no_event_loop_stopped_error() -> None:
    shutdown, _ = _coordinator()

    shutdown.request("cmd_q")
    await asyncio.wait_for(shutdown.finished.wait(), timeout=2.0)

    assert shutdown.finished.is_set()


async def test_no_event_loop_stopped_before_future() -> None:
    shutdown, _ = _coordinator()

    shutdown.request("about_to_quit")
    await asyncio.wait_for(shutdown.finished.wait(), timeout=2.0)

    assert shutdown.finished.is_set()
