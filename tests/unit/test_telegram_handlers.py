"""Полный путь Telegram-команд: CommandBus → Handler → Service → (фейковый) API."""

from __future__ import annotations

from app.buses import CommandBus, EventBus
from app.core.commands import SendTestMessage, VerifyTelegram
from app.core.models.telegram import TelegramBotInfo, TelegramChatInfo
from app.infrastructure.telegram.formatting import TelegramNotificationFormatter
from app.services.telegram import (
    RateLimiter,
    SendTestMessageHandler,
    TelegramService,
    VerifyTelegramHandler,
)


class _FakeApi:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def get_me(self) -> TelegramBotInfo:
        return TelegramBotInfo(id=1, username="logist_bot")

    async def get_chat(self, chat_id: str) -> TelegramChatInfo:
        return TelegramChatInfo(id=2, type="private", title="Тест")

    async def send_message(
        self, chat_id: str, text: str, *, parse_mode: str | None = "HTML"
    ) -> int:
        self.sent.append(text)
        return 1

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
        return None


def _make() -> tuple[CommandBus, _FakeApi]:
    api = _FakeApi()
    service = TelegramService(
        api_factory=lambda token: api,
        formatter=TelegramNotificationFormatter(),
        event_bus=EventBus(),
        token_provider=lambda: "t",
        chat_id_provider=lambda: "c",
        rate_limiter=RateLimiter(min_interval=0),
    )
    bus = CommandBus()
    bus.register(VerifyTelegram, VerifyTelegramHandler(service))
    bus.register(SendTestMessage, SendTestMessageHandler(service))
    return bus, api


async def test_verify_telegram_full_path() -> None:
    bus, api = _make()

    result = await bus.dispatch(VerifyTelegram(token="form-token", chat_id="form-chat"))

    assert result.ok  # типизированный результат дошёл через CommandBus
    assert result.bot_username == "logist_bot"
    assert len(api.sent) == 1


async def test_send_test_message_full_path() -> None:
    bus, api = _make()

    await bus.dispatch(SendTestMessage(token="form-token", chat_id="form-chat"))

    assert len(api.sent) == 1
    assert "LogistAI" in api.sent[0]
