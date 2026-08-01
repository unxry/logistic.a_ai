"""Команды Telegram."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.commands.base import Command
from app.core.models.verification import VerificationResult


@dataclass(frozen=True, slots=True)
class VerifyTelegram(Command[VerificationResult]):
    """Проверить связку токен + чат (getMe → getChat → тестовое сообщение).

    Значения берутся из формы настроек (могут быть ещё не сохранены).
    """

    token: str
    chat_id: str


@dataclass(frozen=True, slots=True)
class SendTestMessage(Command[None]):
    """Отправить тестовое сообщение в указанный чат."""

    token: str
    chat_id: str
