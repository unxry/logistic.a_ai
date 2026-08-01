"""Канал нативных уведомлений macOS.

Dev-режим — ``osascript display notification`` (работает без бандла);
после упаковки в .app канал переключится на UNUserNotificationCenter
(ADR-0002, roadmap v0.5). Порт скрывает разницу.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter

from app.core.models.notification import DeliveryResult, Notification

CHANNEL_ID = "macos_native"

# Исполнитель AppleScript: подменяется в тестах (реальный osascript не нужен).
ScriptRunner = Callable[[str], Awaitable[bool]]


async def _osascript_runner(script: str) -> bool:
    """Выполнить AppleScript; успех — код возврата 0."""
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        script,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await process.wait() == 0


def _escape(text: str) -> str:
    """Экранировать строку для AppleScript (кавычки и обратные слэши)."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


class MacOSNotificationChannel:
    """NotificationChannel для нативных уведомлений macOS."""

    def __init__(self, runner: ScriptRunner | None = None) -> None:
        self._runner = runner if runner is not None else _osascript_runner

    @property
    def channel_id(self) -> str:
        """Идентификатор канала."""
        return CHANNEL_ID

    async def send(self, notification: Notification, text: str) -> DeliveryResult:
        """Показать уведомление; исключений не бросает."""
        started = perf_counter()
        script = (
            f'display notification "{_escape(text)}" with title "{_escape(notification.title)}"'
        )
        try:
            ok = await self._runner(script)
        except Exception as exc:  # osascript отсутствует (не macOS) и т.п.
            return DeliveryResult(channel_id=CHANNEL_ID, ok=False, error=str(exc))
        duration_ms = int((perf_counter() - started) * 1000)
        if not ok:
            return DeliveryResult(
                channel_id=CHANNEL_ID,
                ok=False,
                error="osascript завершился с ошибкой",
                duration_ms=duration_ms,
            )
        return DeliveryResult(channel_id=CHANNEL_ID, ok=True, duration_ms=duration_ms)
