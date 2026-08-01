"""Обработчики Telegram-команд (регистрируются в bootstrap).

Полный поток: UI → CommandBus → Handler → TelegramService → TelegramApi →
Telegram Bot API.
"""

from __future__ import annotations

from app.core.commands import SendTestMessage, VerifyTelegram
from app.core.models.verification import VerificationResult
from app.services.telegram.service import TelegramService


class VerifyTelegramHandler:
    """VerifyTelegram → полная проверка подключения."""

    def __init__(self, telegram_service: TelegramService) -> None:
        self._telegram = telegram_service

    async def __call__(self, command: VerifyTelegram) -> VerificationResult:
        """Выполнить проверку токена и чата из формы настроек."""
        return await self._telegram.verify(command.token, command.chat_id)


class SendTestMessageHandler:
    """SendTestMessage → отправка тестового сообщения."""

    def __init__(self, telegram_service: TelegramService) -> None:
        self._telegram = telegram_service

    async def __call__(self, command: SendTestMessage) -> None:
        """Отправить тестовое сообщение в чат из формы настроек."""
        await self._telegram.send_test_message(command.token, command.chat_id)
