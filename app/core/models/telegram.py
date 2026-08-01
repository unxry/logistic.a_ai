"""Модели данных Telegram (ответы Bot API, нормализованные для домена)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelegramBotInfo:
    """Информация о боте (getMe)."""

    id: int
    username: str
    first_name: str = ""


@dataclass(frozen=True, slots=True)
class TelegramChatInfo:
    """Информация о чате (getChat)."""

    id: int
    type: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class TelegramButton:
    """Кнопка inline-клавиатуры: либо ссылка, либо callback (Stage 9.7)."""

    text: str
    url: str = ""
    callback_data: str = ""


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    """Входящее обновление бота (плоская форма: команда или callback)."""

    update_id: int
    chat_id: str = ""
    message_text: str = ""
    callback_id: str = ""
    callback_data: str = ""
