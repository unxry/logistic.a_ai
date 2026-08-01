"""TelegramBotService — production-бот LogistAI (Stage 9.7).

Long polling поверх порта TelegramApi. Бот знает ТОЛЬКО:
- роутер команд (обработчики собирает composition root);
- callback-кнопки уведомлений (details/ignore — провайдеры инжектируются).

Ни ATI, ни Search Engine бот не импортирует. Безопасность: отвечает только
настроенному chat_id (чужие чаты игнорируются молча), значения токена и
chat_id в логи не пишутся, callback_data валидируется по whitelist.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable

from app.core.errors import SecretStoreError, TelegramError
from app.core.models.telegram import TelegramUpdate
from app.core.ports import TelegramApi, TelegramApiFactory
from app.services.telegram.rate_limiter import RateLimiter
from app.services.telegram.router import TelegramCommandRouter

logger = logging.getLogger(__name__)

#: Разрешённые callback-действия (whitelist) и формат полезной нагрузки.
CALLBACK_ACTIONS = ("details", "ignore")
CALLBACK_PAYLOAD_PATTERN = re.compile(r"[A-Za-z0-9_.\-]{1,48}")
_CALLBACK_PATTERN = re.compile(r"^(details|ignore):([A-Za-z0-9_.\-]{1,48})$")
_POLL_ERROR_PAUSE_SECONDS = 5.0


class TelegramBotService:
    """Поллинг обновлений, команды и callback-кнопки."""

    def __init__(
        self,
        *,
        api_factory: TelegramApiFactory,
        token_provider: Callable[[], str | None],
        chat_id_provider: Callable[[], str],
        router: TelegramCommandRouter,
        details_provider: Callable[[str], Awaitable[str | None]] | None = None,
        ignore_sink: Callable[[str], None] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._api_factory = api_factory
        self._token_provider = token_provider
        self._chat_id_provider = chat_id_provider
        self._router = router
        self._details_provider = details_provider
        self._ignore_sink = ignore_sink
        self._rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()

        self._api: TelegramApi | None = None
        self._offset = 0
        self._task: asyncio.Task[None] | None = None

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        """Идёт ли поллинг."""
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        """Запустить поллинг; ``False`` — токен не настроен (бот молчит)."""
        token = self._safe_token()
        if not token:
            logger.info("Telegram-бот не запущен: токен не настроен")
            return False
        if self.running:
            return True
        self._api = self._api_factory(token)
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._poll_forever())
        logger.info("Telegram-бот запущен (long polling)")
        return True

    async def stop(self) -> None:
        """Остановить поллинг и закрыть клиента (graceful)."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._api is not None:
            await self._api.aclose()
            self._api = None
        logger.info("Telegram-бот остановлен")

    # ── Поллинг ───────────────────────────────────────────────────────────────

    async def _poll_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                logger.warning("Telegram-бот: ошибка поллинга — %s", type(exc).__name__)
                await asyncio.sleep(_POLL_ERROR_PAUSE_SECONDS)
            except Exception:
                logger.exception("Telegram-бот: неожиданная ошибка поллинга")
                await asyncio.sleep(_POLL_ERROR_PAUSE_SECONDS)

    async def poll_once(self) -> int:
        """Забрать и обработать пачку обновлений; вернуть число обработанных."""
        api = self._api
        if api is None:
            return 0
        updates = await api.get_updates(self._offset)
        handled = 0
        for update in updates:
            self._offset = max(self._offset, update.update_id + 1)
            await self._handle(api, update)
            handled += 1
        return handled

    # ── Обработка обновлений ──────────────────────────────────────────────────

    async def _handle(self, api: TelegramApi, update: TelegramUpdate) -> None:
        authorized_chat = self._chat_id_provider()
        if not authorized_chat or update.chat_id != authorized_chat:
            # Чужой чат: молча игнорируем; значения chat_id НЕ логируются.
            logger.info("Telegram-бот: обновление из неавторизованного чата пропущено")
            if update.callback_id:
                await self._safe_answer(api, update.callback_id, "Недоступно")
            return
        if update.callback_id:
            await self._handle_callback(api, update, authorized_chat)
            return
        if update.message_text:
            reply = await self._router.dispatch(update.message_text)
            if reply:
                await self._send(api, authorized_chat, reply)

    async def _handle_callback(
        self, api: TelegramApi, update: TelegramUpdate, chat_id: str
    ) -> None:
        match = _CALLBACK_PATTERN.match(update.callback_data)
        if match is None:
            # Невалидный callback_data (подделка/устаревший формат) — только ack.
            logger.warning("Telegram-бот: невалидный callback_data отклонён")
            await self._safe_answer(api, update.callback_id, "Кнопка устарела")
            return
        action, cargo_id = match.group(1), match.group(2)
        if action == "ignore":
            if self._ignore_sink is not None:
                self._ignore_sink(cargo_id)
            await self._safe_answer(api, update.callback_id, "Груз скрыт")
            return
        # details
        details = (
            await self._details_provider(cargo_id) if self._details_provider is not None else None
        )
        await self._safe_answer(api, update.callback_id)
        if details:
            await self._send(api, chat_id, details)
        else:
            await self._send(api, chat_id, "ℹ️ Груз уже недоступен (устарел или скрыт).")

    # ── Отправка ──────────────────────────────────────────────────────────────

    async def _send(self, api: TelegramApi, chat_id: str, text: str) -> None:
        await self._rate_limiter.wait()
        try:
            await api.send_message(chat_id, text)
        except TelegramError as exc:
            logger.warning("Telegram-бот: ответ не доставлен — %s", type(exc).__name__)

    @staticmethod
    async def _safe_answer(api: TelegramApi, callback_id: str, text: str = "") -> None:
        try:
            await api.answer_callback_query(callback_id, text=text)
        except TelegramError as exc:
            logger.warning("Telegram-бот: ack кнопки не доставлен — %s", type(exc).__name__)

    def _safe_token(self) -> str | None:
        try:
            return self._token_provider()
        except SecretStoreError:
            logger.warning("Telegram-бот: хранилище секретов недоступно")
            return None
