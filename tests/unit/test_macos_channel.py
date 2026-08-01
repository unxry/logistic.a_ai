"""Тесты канала нативных уведомлений macOS (runner подменяется)."""

from __future__ import annotations

from app.core.models.notification import Notification
from app.core.ports import NotificationChannel
from app.infrastructure.notifications.macos import MacOSNotificationChannel


async def test_channel_sends_via_runner() -> None:
    scripts: list[str] = []

    async def runner(script: str) -> bool:
        scripts.append(script)
        return True

    channel = MacOSNotificationChannel(runner=runner)
    result = await channel.send(Notification.create("Груз найден", ""), "Москва → Казань")

    assert result.ok and result.channel_id == "macos_native"
    assert 'with title "Груз найден"' in scripts[0]
    assert '"Москва → Казань"' in scripts[0]


async def test_channel_escapes_quotes() -> None:
    scripts: list[str] = []

    async def runner(script: str) -> bool:
        scripts.append(script)
        return True

    channel = MacOSNotificationChannel(runner=runner)
    await channel.send(Notification.create('Груз "Срочно"', ""), 'текст с "кавычками"')

    assert '\\"Срочно\\"' in scripts[0]
    assert '\\"кавычками\\"' in scripts[0]


async def test_channel_failure_returns_result() -> None:
    async def runner(script: str) -> bool:
        return False

    result = await MacOSNotificationChannel(runner=runner).send(Notification.create("З", ""), "т")
    assert not result.ok
    assert result.error is not None


async def test_channel_exception_wrapped() -> None:
    async def runner(script: str) -> bool:
        raise FileNotFoundError("osascript не найден")

    result = await MacOSNotificationChannel(runner=runner).send(Notification.create("З", ""), "т")
    assert not result.ok
    assert "osascript" in (result.error or "")


def test_channel_satisfies_port() -> None:
    assert isinstance(MacOSNotificationChannel(), NotificationChannel)
