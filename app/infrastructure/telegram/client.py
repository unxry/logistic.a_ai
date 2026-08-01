"""TelegramClient — httpx-реализация порта TelegramApi.

Production-требования (ADR-0012):
- один ``httpx.AsyncClient`` на весь жизненный цикл (не на запрос), ``aclose()``;
- таймауты: connect 5 с / read 10 с / write 10 с / pool 5 с;
- ретраи по RetryPolicy (429 → retry_after; 5xx/сеть → экспонента с джиттером);
- все сырые ошибки транслируются в доменные ``TelegramError``;
- БЕЗОПАСНОСТЬ: Bot Token не попадает ни в логи, ни в тексты исключений —
  URL Telegram содержит токен, поэтому сообщения санитизируются, а логгеры
  httpx/httpcore приглушены до WARNING (их INFO-логи печатают полный URL).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.errors import (
    TelegramAPIError,
    TelegramAuthError,
    TelegramChatNotFoundError,
    TelegramError,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.core.models.telegram import (
    TelegramBotInfo,
    TelegramButton,
    TelegramChatInfo,
    TelegramUpdate,
)
from app.infrastructure.telegram.retry import RetryPolicy

logger = logging.getLogger(__name__)

_TOKEN_MASK = "***TOKEN***"
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
#: Long polling ждёт дольше обычного read-таймаута.
_POLL_TIMEOUT = httpx.Timeout(connect=5.0, read=40.0, write=10.0, pool=5.0)
#: Лимит Telegram на длину текста одного сообщения.
MESSAGE_LIMIT = 4096


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> tuple[str, ...]:
    """Разбить длинное сообщение по границам строк (чанки ≤ limit)."""
    if len(text) <= limit:
        return (text,)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        while len(line) > limit:  # аварийный случай: одна строка длиннее лимита
            chunks.append(line[:limit])
            line = line[limit:]
        extra = len(line) + (1 if current else 0)
        if current_len + extra > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += extra
    if current:
        chunks.append("\n".join(current))
    return tuple(chunks)


class TelegramClient:
    """Клиент Telegram Bot API (реализация порта TelegramApi)."""

    def __init__(
        self,
        token: str,
        *,
        retry_policy: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # INFO-логи httpx печатают полный URL запроса, а URL Bot API содержит
        # токен — приглушаем до WARNING (идемпотентно).
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

        self._token = token
        self._retry = retry_policy if retry_policy is not None else RetryPolicy()
        self._client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=_TIMEOUT,
            transport=transport,
        )

    # ── Порт TelegramApi ──────────────────────────────────────────────────────

    async def get_me(self) -> TelegramBotInfo:
        """Проверить токен и получить информацию о боте."""
        result = await self._call("getMe")
        return TelegramBotInfo(
            id=int(result.get("id", 0)),
            username=str(result.get("username", "")),
            first_name=str(result.get("first_name", "")),
        )

    async def get_chat(self, chat_id: str) -> TelegramChatInfo:
        """Проверить доступность чата."""
        result = await self._call("getChat", {"chat_id": chat_id})
        title = result.get("title") or result.get("username") or result.get("first_name") or ""
        return TelegramChatInfo(
            id=int(result.get("id", 0)),
            type=str(result.get("type", "")),
            title=str(title),
        )

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        buttons: tuple[TelegramButton, ...] = (),
    ) -> int:
        """Отправить текст (+inline-кнопки); длинный текст режется на чанки.

        Клавиатура прикрепляется только к последнему чанку — кнопки видны
        под завершённым сообщением.
        """
        chunks = split_message(text)
        message_id = 0
        for index, chunk in enumerate(chunks):
            params: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if parse_mode is not None:
                params["parse_mode"] = parse_mode
            if buttons and index == len(chunks) - 1:
                params["reply_markup"] = self._inline_keyboard(buttons)
            result = await self._call("sendMessage", params)
            message_id = int(result.get("message_id", 0))
        return message_id

    async def get_updates(
        self, offset: int, *, timeout_seconds: int = 25
    ) -> tuple[TelegramUpdate, ...]:
        """Long polling getUpdates (только сообщения и callback-кнопки)."""
        result = await self._call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout_seconds,
                "allowed_updates": ["message", "callback_query"],
            },
            timeout=_POLL_TIMEOUT,
        )
        raw_updates = result.get("updates", []) if isinstance(result, dict) else []
        return tuple(self._parse_update(item) for item in raw_updates if isinstance(item, dict))

    async def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> None:
        """Подтвердить нажатие кнопки (убирает «часики» у пользователя)."""
        params: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = text
        await self._call("answerCallbackQuery", params)

    async def send_photo(
        self,
        chat_id: str,
        photo: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> int:
        """Отправить фото (file_id или URL); вернуть message_id."""
        params: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            params["caption"] = caption
        if parse_mode is not None:
            params["parse_mode"] = parse_mode
        result = await self._call("sendPhoto", params)
        return int(result.get("message_id", 0))

    async def send_document(
        self,
        chat_id: str,
        document: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> int:
        """Отправить документ (file_id или URL); вернуть message_id."""
        params: dict[str, Any] = {"chat_id": chat_id, "document": document}
        if caption is not None:
            params["caption"] = caption
        if parse_mode is not None:
            params["parse_mode"] = parse_mode
        result = await self._call("sendDocument", params)
        return int(result.get("message_id", 0))

    async def aclose(self) -> None:
        """Закрыть httpx-клиент."""
        await self._client.aclose()

    # ── Внутреннее ────────────────────────────────────────────────────────────

    async def _call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: httpx.Timeout | None = None,
    ) -> dict[str, Any]:
        """Вызов метода Bot API с ретраями по политике."""
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self._attempt(method, dict(params or {}), timeout=timeout)
            except TelegramError as error:
                if not _is_retryable(error) or attempt >= self._retry.max_attempts:
                    raise
                delay = (
                    error.retry_after
                    if isinstance(error, TelegramRateLimitError)
                    else self._retry.delay_for(attempt)
                )
                logger.warning(
                    "Telegram %s: попытка %d/%d не удалась (%s), повтор через %.2f с",
                    method,
                    attempt,
                    self._retry.max_attempts,
                    type(error).__name__,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _attempt(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: httpx.Timeout | None = None,
    ) -> dict[str, Any]:
        """Одна попытка вызова: HTTP → разбор → доменный результат или ошибка."""
        try:
            response = await self._client.post(
                f"/{method}", json=params, timeout=timeout if timeout is not None else _TIMEOUT
            )
        except httpx.TimeoutException as exc:
            raise TelegramNetworkError(f"Таймаут Telegram ({method})") from exc
        except httpx.TransportError as exc:
            raise TelegramNetworkError(
                f"Сетевая ошибка Telegram ({method}): {self._sanitize(str(exc))}"
            ) from exc

        data: Any = None
        try:
            data = response.json()
        except ValueError:
            data = None

        if response.status_code == 200 and isinstance(data, dict) and data.get("ok"):
            result = data.get("result")
            if isinstance(result, dict):
                return result
            if isinstance(result, list):  # getUpdates отдаёт массив
                return {"updates": result}
            return {}
        raise self._map_error(response.status_code, data)

    def _map_error(self, status: int, data: Any) -> TelegramError:
        """HTTP-статус + тело ответа → доменная ошибка."""
        description = "нет описания"
        retry_after: float | None = None
        if isinstance(data, dict):
            description = self._sanitize(str(data.get("description", description)))
            parameters = data.get("parameters")
            if isinstance(parameters, dict) and "retry_after" in parameters:
                retry_after = float(parameters["retry_after"])

        if status == 401:
            return TelegramAuthError(f"Неверный Bot Token: {description}")
        if status == 404:
            return TelegramAuthError("Неверный Bot Token (Telegram не нашёл такого бота)")
        if status == 429:
            return TelegramRateLimitError(retry_after if retry_after is not None else 1.0)
        if status == 400 and "chat not found" in description.lower():
            return TelegramChatNotFoundError(f"Чат не найден: {description}")
        return TelegramAPIError(status, description)

    @staticmethod
    def _inline_keyboard(buttons: tuple[TelegramButton, ...]) -> str:
        """Кнопки → JSON inline_keyboard (по одной в ряд — читаемо на телефоне)."""
        rows = []
        for button in buttons:
            entry: dict[str, str] = {"text": button.text}
            if button.url:
                entry["url"] = button.url
            elif button.callback_data:
                entry["callback_data"] = button.callback_data[:64]  # лимит Telegram
            else:
                continue
            rows.append([entry])
        return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)

    @staticmethod
    def _parse_update(item: dict[str, Any]) -> TelegramUpdate:
        """Сырое обновление → плоская модель (сообщение или callback)."""

        def dict_field(container: Mapping[str, Any], key: str) -> dict[str, Any]:
            value = container.get(key)
            return value if isinstance(value, dict) else {}

        message = dict_field(item, "message")
        callback = dict_field(item, "callback_query")
        chat = dict_field(message, "chat")
        callback_chat = dict_field(dict_field(callback, "message"), "chat")
        chat_id = chat.get("id", callback_chat.get("id", ""))
        return TelegramUpdate(
            update_id=int(item.get("update_id", 0)),
            chat_id=str(chat_id) if chat_id != "" else "",
            message_text=str(message.get("text", "")),
            callback_id=str(callback.get("id", "")),
            callback_data=str(callback.get("data", "")),
        )

    def _sanitize(self, text: str) -> str:
        """Убрать Bot Token из любых сообщений (URL httpx содержит токен)."""
        if self._token and self._token in text:
            return text.replace(self._token, _TOKEN_MASK)
        return text


def _is_retryable(error: TelegramError) -> bool:
    """Повторять только то, что может исправиться само: сеть, 5xx, 429."""
    if isinstance(error, TelegramNetworkError | TelegramRateLimitError):
        return True
    return isinstance(error, TelegramAPIError) and 500 <= error.code < 600
