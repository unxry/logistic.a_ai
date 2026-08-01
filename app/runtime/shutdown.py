"""Application shutdown lifecycle for qasync/Qt."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol

from app.core.commands import Command, StopScheduler
from app.core.events import AppClosing, Event
from app.ui.theme import AnimationManager

logger = logging.getLogger(__name__)


class _EventBusLike(Protocol):
    def publish(self, event: Event) -> None: ...


class _CommandBusLike(Protocol):
    async def dispatch[R](self, command: Command[R]) -> R: ...


class _TelegramBotLike(Protocol):
    async def stop(self) -> None: ...


class _RecommendationPipelineLike(Protocol):
    async def wait_idle(self) -> None: ...


class _AtiClientLike(Protocol):
    async def aclose(self) -> None: ...


class _DatabaseLike(Protocol):
    def close(self) -> None: ...


class ShutdownCoordinator:
    """Idempotent async shutdown sequence.

    The coordinator deliberately does not call ``loop.stop()``. qasync keeps
    running until ``finished.wait()`` completes; Qt is asked to quit only after
    service cleanup is done.
    """

    def __init__(
        self,
        *,
        event_bus: _EventBusLike,
        command_bus: _CommandBusLike,
        telegram_bot: _TelegramBotLike,
        recommendation_pipeline: _RecommendationPipelineLike,
        ati_client: _AtiClientLike,
        database: _DatabaseLike,
        menu_bar: object | None = None,
        startup_tasks: Iterable[asyncio.Task[object]] = (),
        timeout_seconds: float = 10.0,
    ) -> None:
        self._event_bus = event_bus
        self._command_bus = command_bus
        self._telegram_bot = telegram_bot
        self._recommendation_pipeline = recommendation_pipeline
        self._ati_client = ati_client
        self._database = database
        self._menu_bar = menu_bar
        self._startup_tasks = set(startup_tasks)
        self._timeout_seconds = timeout_seconds
        self._finished = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._requested = False

    @property
    def finished(self) -> asyncio.Event:
        return self._finished

    @property
    def is_requested(self) -> bool:
        return self._requested

    def add_startup_task(self, task: asyncio.Task[object]) -> None:
        self._startup_tasks.add(task)

    def set_menu_bar(self, menu_bar: object | None) -> None:
        self._menu_bar = menu_bar

    def request(self, reason: str = "quit") -> None:
        """Schedule shutdown once."""
        if self._requested:
            return
        self._requested = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Signal handlers and tests may request shutdown just before qasync
            # enters the loop. Queue cleanup on the configured loop instead of
            # stopping Qt early or raising from the signal callback.
            loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run(reason))

    async def shutdown_now(self, reason: str = "test") -> None:
        """Run shutdown directly in tests."""
        if self._requested:
            await self._finished.wait()
            return
        self._requested = True
        await self._run(reason)

    async def _run(self, reason: str) -> None:
        logger.info("Shutdown requested: %s", reason)
        try:
            await asyncio.wait_for(self._cleanup(reason), timeout=self._timeout_seconds)
        except TimeoutError:
            self._log_pending_tasks()
            logger.error("Shutdown cleanup timeout after %.1f seconds", self._timeout_seconds)
        except Exception:
            logger.exception("Shutdown cleanup failed")
        finally:
            self._finished.set()

    async def _cleanup(self, reason: str) -> None:
        publish = getattr(self._event_bus, "publish", None)
        if callable(publish):
            publish(AppClosing())

        detach = getattr(self._menu_bar, "detach", None)
        if callable(detach):
            detach()
        AnimationManager.instance().stop_all()

        await self._cancel_startup_tasks()
        await self._maybe_await(lambda: self._command_bus.dispatch(StopScheduler()))
        await self._maybe_await(lambda: self._telegram_bot.stop())
        await self._maybe_await(lambda: self._recommendation_pipeline.wait_idle())
        await self._maybe_await(lambda: self._ati_client.aclose())

        close = getattr(self._database, "close", None)
        if callable(close):
            close()
        logger.info("Shutdown completed: %s", reason)

    async def _cancel_startup_tasks(self) -> None:
        tasks = {task for task in self._startup_tasks if not task.done()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _maybe_await(self, factory: Callable[[], Awaitable[object]]) -> None:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Shutdown step failed")

    def _log_pending_tasks(self) -> None:
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        if pending:
            logger.warning("Pending asyncio tasks during shutdown: %d", len(pending))
