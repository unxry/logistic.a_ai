"""Тесты TelegramService: машина состояний, verify, канал доставки, безопасность."""

from __future__ import annotations

import logging

import pytest

from app.buses import EventBus
from app.core.errors import (
    TelegramAuthError,
    TelegramChatNotFoundError,
    TelegramError,
    TelegramNetworkError,
)
from app.core.events import TelegramStatusChanged
from app.core.models.connection import ConnectionState
from app.core.models.notification import Notification
from app.core.models.telegram import TelegramBotInfo, TelegramChatInfo
from app.core.ports import NotificationChannel
from app.infrastructure.telegram.formatting import TelegramNotificationFormatter
from app.services.telegram import RateLimiter, TelegramService

TOKEN = "SECRET-TOKEN-999"
CHAT_ID = "CHAT-ID-777001"


class FakeTelegramApi:
    """Фейк порта TelegramApi с программируемыми ошибками."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.get_me_error: TelegramError | None = None
        self.get_chat_error: TelegramError | None = None
        self.send_error: TelegramError | None = None
        self.closed = False

    async def get_me(self) -> TelegramBotInfo:
        if self.get_me_error is not None:
            raise self.get_me_error
        return TelegramBotInfo(id=1, username="logist_bot")

    async def get_chat(self, chat_id: str) -> TelegramChatInfo:
        if self.get_chat_error is not None:
            raise self.get_chat_error
        return TelegramChatInfo(id=5, type="private", title="Иван")

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        buttons: tuple[object, ...] = (),
    ) -> int:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((chat_id, text))
        self.buttons = buttons
        return 42

    async def send_photo(
        self,
        chat_id: str,
        photo: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> int:
        return 0

    async def send_document(
        self,
        chat_id: str,
        document: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> int:
        return 0

    async def aclose(self) -> None:
        self.closed = True


class Harness:
    """Собранный сервис + фейки + коллектор статусов."""

    def __init__(self, token: str | None = TOKEN) -> None:
        self.api = FakeTelegramApi()
        self.bus = EventBus()
        self.token: str | None = token
        self.states: list[TelegramStatusChanged] = []
        self.bus.subscribe(TelegramStatusChanged, self.states.append)

        self.service = TelegramService(
            api_factory=lambda token: self.api,
            formatter=TelegramNotificationFormatter(),
            event_bus=self.bus,
            token_provider=lambda: self.token,
            chat_id_provider=lambda: CHAT_ID,
            rate_limiter=RateLimiter(min_interval=0),
        )

    def state_values(self) -> list[ConnectionState]:
        return [event.state for event in self.states]


def test_service_satisfies_channel_port() -> None:
    assert isinstance(Harness().service, NotificationChannel)


async def test_verify_success_full_details() -> None:
    h = Harness()
    result = await h.service.verify(TOKEN, CHAT_ID)

    assert result.ok
    assert result.bot_username == "logist_bot"
    assert result.chat_title == "Иван"
    assert h.state_values() == [ConnectionState.CONNECTING, ConnectionState.CONNECTED]
    assert len(h.api.sent) == 1  # тестовое сообщение ушло
    assert h.api.closed  # временный клиент закрыт


async def test_verify_bad_token() -> None:
    h = Harness()
    h.api.get_me_error = TelegramAuthError("Неверный Bot Token")

    result = await h.service.verify(TOKEN, CHAT_ID)

    assert not result.token_ok and not result.ok
    assert h.state_values() == [ConnectionState.CONNECTING, ConnectionState.ERROR]


async def test_verify_chat_not_found_gives_start_hint() -> None:
    h = Harness()
    h.api.get_chat_error = TelegramChatNotFoundError("chat not found")

    result = await h.service.verify(TOKEN, CHAT_ID)

    assert result.token_ok and not result.chat_ok
    assert result.error is not None and "Start" in result.error


async def test_channel_send_success() -> None:
    h = Harness()
    result = await h.service.send(Notification.create("Заголовок", "тело"), "готовый текст")

    assert result.ok
    assert result.channel_id == "telegram"
    assert h.api.sent == [(CHAT_ID, "готовый текст")]  # канал шлёт ГОТОВЫЙ текст
    assert h.service.state is ConnectionState.CONNECTED


async def test_channel_send_failure_returns_result_not_raises() -> None:
    h = Harness()
    h.api.send_error = TelegramNetworkError("обрыв связи")

    result = await h.service.send(Notification.create("З", "т"), "текст")

    assert not result.ok
    assert result.error is not None and "обрыв" in result.error
    assert h.service.state is ConnectionState.ERROR


async def test_channel_send_unconfigured() -> None:
    h = Harness(token=None)
    result = await h.service.send(Notification.create("З", "т"), "текст")

    assert not result.ok
    assert result.error is not None and "не настроен" in result.error


async def test_successful_send_heals_error_state() -> None:
    h = Harness()
    h.api.send_error = TelegramNetworkError("обрыв")
    await h.service.send(Notification.create("Первое", ""), "т1")
    assert h.service.state is ConnectionState.ERROR

    h.api.send_error = None
    await h.service.send(Notification.create("Второе", ""), "т2")
    assert h.service.state is ConnectionState.CONNECTED
    await h.service.aclose()


async def test_secrets_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Безопасность: ни токен, ни chat_id не попадают в логи сервиса."""
    h = Harness()
    with caplog.at_level(logging.DEBUG):
        await h.service.verify(TOKEN, CHAT_ID)
        await h.service.send(Notification.create("Тест", "тело"), "текст")

    assert TOKEN not in caplog.text
    assert CHAT_ID not in caplog.text
    await h.service.aclose()


async def test_custom_channel_id_for_second_bot() -> None:
    """Мультибот: второй TelegramService с другим channel_id."""
    h = Harness()
    second = TelegramService(
        api_factory=lambda token: h.api,
        formatter=TelegramNotificationFormatter(),
        event_bus=h.bus,
        token_provider=lambda: TOKEN,
        chat_id_provider=lambda: CHAT_ID,
        rate_limiter=RateLimiter(min_interval=0),
        channel_id="telegram_backup",
    )
    result = await second.send(Notification.create("З", "т"), "текст")
    assert result.channel_id == "telegram_backup"
