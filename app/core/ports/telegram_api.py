"""Порт Telegram Bot API.

Application-сервис работает с этим контрактом; httpx-реализация
(``TelegramClient``) живёт в инфраструктуре — контракт
«services → только core» сохраняется.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.core.models.telegram import (
    TelegramBotInfo,
    TelegramButton,
    TelegramChatInfo,
    TelegramUpdate,
)


class TelegramApi(Protocol):
    """Минимальный контракт Bot API, нужный приложению.

    Все методы бросают только доменные ``TelegramError``-исключения.
    """

    async def get_me(self) -> TelegramBotInfo:
        """Проверить токен и получить информацию о боте."""
        ...

    async def get_chat(self, chat_id: str) -> TelegramChatInfo:
        """Проверить доступность чата."""
        ...

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        buttons: tuple[TelegramButton, ...] = (),
    ) -> int:
        """Отправить текст (+inline-кнопки); вернуть message_id."""
        ...

    async def get_updates(
        self, offset: int, *, timeout_seconds: int = 25
    ) -> tuple[TelegramUpdate, ...]:
        """Long polling: обновления начиная с ``offset`` (Stage 9.7)."""
        ...

    async def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> None:
        """Подтвердить нажатие inline-кнопки (Stage 9.7)."""
        ...

    async def send_photo(
        self,
        chat_id: str,
        photo: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> int:
        """Отправить фото (file_id или URL); вернуть message_id."""
        ...

    async def send_document(
        self,
        chat_id: str,
        document: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> int:
        """Отправить документ (file_id или URL); вернуть message_id."""
        ...

    async def aclose(self) -> None:
        """Закрыть сетевые ресурсы."""
        ...


# Фабрика клиента: сервис пересоздаёт API при смене токена, не зная реализации.
type TelegramApiFactory = Callable[[str], TelegramApi]
