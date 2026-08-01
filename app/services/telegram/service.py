"""TelegramService — подключение к Telegram и канал доставки (application-слой).

С этапа 3.5 Telegram — обычный consumer Notification Center: сервис реализует
порт ``NotificationChannel`` (``channel_id`` + ``send``) и регистрируется в
ChannelRegistry. Общая очередь и события доставки живут в NotificationService;
здесь остались: машина состояний, verify, тестовые сообщения, RateLimiter
(лимит Telegram — 1 сообщение в секунду на чат) и управление клиентом.

Машина состояний: DISCONNECTED → CONNECTING → CONNECTED / ERROR; каждое
изменение публикуется как ``TelegramStatusChanged``. Успешная отправка
«лечит» состояние ERROR.

БЕЗОПАСНОСТЬ: токен и chat_id в логи не пишутся никогда.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import perf_counter

from app.core.errors import (
    SecretStoreError,
    TelegramAuthError,
    TelegramChatNotFoundError,
    TelegramError,
    TelegramNetworkError,
)
from app.core.events import TelegramStatusChanged
from app.core.models.connection import ConnectionState
from app.core.models.notification import DeliveryResult, Notification
from app.core.models.telegram import TelegramButton
from app.core.models.verification import VerificationResult
from app.core.ports import EventPublisher, NotificationFormatter, TelegramApi, TelegramApiFactory
from app.services.telegram.bot import CALLBACK_ACTIONS, CALLBACK_PAYLOAD_PATTERN
from app.services.telegram.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

CHANNEL_ID = "telegram"


def _buttons_from_actions(notification: Notification) -> tuple[TelegramButton, ...]:
    """NotificationAction → inline-кнопки (Stage 9.7).

    Действия со ссылкой — url-кнопки; известные callback-действия
    (details/ignore) требуют валидного cargo_id в payload — иначе кнопка
    не создаётся (callback_data всегда проходит валидацию формата).
    """
    cargo_id = str(notification.payload.get("cargo_id", ""))
    cargo_id_ok = bool(CALLBACK_PAYLOAD_PATTERN.fullmatch(cargo_id))
    buttons: list[TelegramButton] = []
    for action in notification.actions:
        if action.url:
            buttons.append(TelegramButton(text=action.label, url=action.url))
        elif action.id in CALLBACK_ACTIONS and cargo_id_ok:
            buttons.append(
                TelegramButton(text=action.label, callback_data=f"{action.id}:{cargo_id}")
            )
    return tuple(buttons)


_HINT_CHAT_NOT_FOUND = (
    "Чат не найден. Откройте диалог с ботом и нажмите Start, затем проверьте Chat ID и повторите."
)


class TelegramService:
    """Верификация, состояние подключения и транспорт-канал Telegram."""

    def __init__(
        self,
        *,
        api_factory: TelegramApiFactory,
        formatter: NotificationFormatter,
        event_bus: EventPublisher,
        token_provider: Callable[[], str | None],
        chat_id_provider: Callable[[], str],
        rate_limiter: RateLimiter | None = None,
        channel_id: str = CHANNEL_ID,
    ) -> None:
        self._api_factory = api_factory
        self._formatter = formatter
        self._events = event_bus
        self._token_provider = token_provider
        self._chat_id_provider = chat_id_provider
        self._rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()
        self._channel_id = channel_id

        self._state = ConnectionState.DISCONNECTED
        self._api: TelegramApi | None = None
        self._api_token: str | None = None

    # ── Состояние ─────────────────────────────────────────────────────────────

    @property
    def state(self) -> ConnectionState:
        """Текущее состояние подключения."""
        return self._state

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        if state is self._state and not detail:
            return
        self._state = state
        logger.info("Telegram: %s%s", state.value, f" — {detail}" if detail else "")
        self._events.publish(TelegramStatusChanged(state=state, detail=detail))

    # ── Порт NotificationChannel (Telegram = обычный канал доставки) ─────────

    @property
    def channel_id(self) -> str:
        """Идентификатор канала (параметризуем — можно второго бота)."""
        return self._channel_id

    async def send(self, notification: Notification, text: str) -> DeliveryResult:
        """Доставить готовый текст; исключений не бросает (контракт порта)."""
        started = perf_counter()
        api = await self._ensure_api()
        chat_id = self._chat_id_provider()
        if api is None or not chat_id:
            return DeliveryResult(
                channel_id=self._channel_id,
                ok=False,
                error="Telegram не настроен: нет токена или Chat ID",
            )

        await self._rate_limiter.wait()
        try:
            await api.send_message(chat_id, text, buttons=_buttons_from_actions(notification))
        except TelegramError as exc:
            if isinstance(exc, TelegramNetworkError | TelegramAuthError):
                self._set_state(ConnectionState.ERROR, type(exc).__name__)
            logger.warning("Telegram: сообщение не доставлено — %s", type(exc).__name__)
            return DeliveryResult(
                channel_id=self._channel_id,
                ok=False,
                error=str(exc),
                duration_ms=int((perf_counter() - started) * 1000),
            )

        duration_ms = int((perf_counter() - started) * 1000)
        logger.info("Telegram: сообщение отправлено за %d мс", duration_ms)
        if self._state is not ConnectionState.CONNECTED:
            self._set_state(ConnectionState.CONNECTED, "отправка успешна")
        return DeliveryResult(channel_id=self._channel_id, ok=True, duration_ms=duration_ms)

    # ── Верификация и тест ────────────────────────────────────────────────────

    async def verify(self, token: str, chat_id: str) -> VerificationResult:
        """Полная проверка: getMe → getChat → тестовое сообщение.

        Значения берутся из формы (могут быть не сохранены), поэтому
        используется временный клиент — основное подключение не трогается.
        """
        self._set_state(ConnectionState.CONNECTING, "проверка подключения")
        api = self._api_factory(token)
        try:
            try:
                bot = await api.get_me()
            except TelegramError as exc:
                return self._verify_failed(
                    VerificationResult(
                        token_ok=False, chat_ok=False, test_sent=False, error=str(exc)
                    )
                )

            try:
                chat = await api.get_chat(chat_id)
            except TelegramChatNotFoundError:
                return self._verify_failed(
                    VerificationResult(
                        token_ok=True,
                        chat_ok=False,
                        test_sent=False,
                        error=_HINT_CHAT_NOT_FOUND,
                        bot_username=bot.username,
                    )
                )
            except TelegramError as exc:
                return self._verify_failed(
                    VerificationResult(
                        token_ok=True,
                        chat_ok=False,
                        test_sent=False,
                        error=str(exc),
                        bot_username=bot.username,
                    )
                )

            try:
                await api.send_message(chat_id, self._formatter.format_test_message())
            except TelegramError as exc:
                return self._verify_failed(
                    VerificationResult(
                        token_ok=True,
                        chat_ok=True,
                        test_sent=False,
                        error=str(exc),
                        bot_username=bot.username,
                        chat_title=chat.title,
                    )
                )

            self._set_state(ConnectionState.CONNECTED, f"бот @{bot.username}")
            return VerificationResult(
                token_ok=True,
                chat_ok=True,
                test_sent=True,
                bot_username=bot.username,
                chat_title=chat.title,
            )
        finally:
            await api.aclose()

    def _verify_failed(self, result: VerificationResult) -> VerificationResult:
        self._set_state(ConnectionState.ERROR, result.error or "проверка не пройдена")
        return result

    async def send_test_message(self, token: str, chat_id: str) -> None:
        """Отправить тестовое сообщение (значения из формы, временный клиент)."""
        api = self._api_factory(token)
        try:
            await api.send_message(chat_id, self._formatter.format_test_message())
            logger.info("Telegram: тестовое сообщение отправлено")
        finally:
            await api.aclose()

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Закрыть сетевые ресурсы (graceful shutdown)."""
        if self._api is not None:
            await self._api.aclose()
            self._api = None
            self._api_token = None
        self._set_state(ConnectionState.DISCONNECTED, "остановка")

    async def _ensure_api(self) -> TelegramApi | None:
        """Актуальный клиент: пересоздаётся при смене токена, None — токена нет."""
        try:
            token = self._token_provider()
        except SecretStoreError:
            logger.warning("Telegram: хранилище секретов недоступно, отправка невозможна")
            return None
        if not token:
            return None
        if self._api is None or self._api_token != token:
            if self._api is not None:
                await self._api.aclose()
            self._api = self._api_factory(token)
            self._api_token = token
        return self._api
