"""Тесты Stage 9.7 — production Telegram: роутер, бот, кнопки, шаблоны, security."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.core.models.logistics.cargo import Cargo
from app.core.models.matching import MatchingWeights
from app.core.models.notification import (
    Notification,
    NotificationAction,
    NotificationCategory,
)
from app.core.models.severity import Severity
from app.core.models.sources import SourceHealth, SourceStatus
from app.core.models.telegram import TelegramButton, TelegramUpdate
from app.infrastructure.telegram import bot_replies
from app.infrastructure.telegram.client import split_message
from app.infrastructure.telegram.formatting import (
    SEPARATOR,
    TelegramNotificationFormatter,
    escape_html,
)
from app.services.telegram.bot import TelegramBotService
from app.services.telegram.router import TelegramCommandRouter
from app.services.telegram.service import _buttons_from_actions

AUTHORIZED_CHAT = "100500"


class FakeBotApi:
    """Фейк порта TelegramApi для бота: очередь обновлений + журнал отправок."""

    def __init__(self) -> None:
        self.updates: list[TelegramUpdate] = []
        self.sent: list[tuple[str, str]] = []
        self.sent_buttons: list[tuple[TelegramButton, ...]] = []
        self.answered: list[tuple[str, str]] = []
        self.closed = False

    async def get_me(self) -> Any:  # pragma: no cover - боту не нужен
        raise NotImplementedError

    async def get_chat(self, chat_id: str) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        buttons: tuple[TelegramButton, ...] = (),
    ) -> int:
        self.sent.append((chat_id, text))
        self.sent_buttons.append(buttons)
        return len(self.sent)

    async def send_photo(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        return 0

    async def send_document(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        return 0

    async def get_updates(
        self, offset: int, *, timeout_seconds: int = 25
    ) -> tuple[TelegramUpdate, ...]:
        batch = tuple(u for u in self.updates if u.update_id >= offset)
        self.updates = []
        return batch

    async def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> None:
        self.answered.append((callback_query_id, text))

    async def aclose(self) -> None:
        self.closed = True


def _bot(api: FakeBotApi, router: TelegramCommandRouter | None = None) -> TelegramBotService:
    details_seen: list[str] = []

    async def details(cargo_id: str) -> str | None:
        details_seen.append(cargo_id)
        return f"<b>Детали {cargo_id}</b>" if cargo_id == "cargo-1" else None

    ignored: list[str] = []
    bot = TelegramBotService(
        api_factory=lambda token: api,
        token_provider=lambda: "token-under-test",
        chat_id_provider=lambda: AUTHORIZED_CHAT,
        router=router if router is not None else TelegramCommandRouter(),
        details_provider=details,
        ignore_sink=ignored.append,
    )
    bot._api = api  # poll_once без start (тесты не крутят цикл)
    bot.test_ignored = ignored  # type: ignore[attr-defined]
    return bot


def _router_with(command: str, reply: str) -> TelegramCommandRouter:
    router = TelegramCommandRouter()

    async def handler(arguments: str) -> str:
        return reply + (f"|{arguments}" if arguments else "")

    router.register(command, handler, description="тест")
    return router


# ── Command Router ───────────────────────────────────────────────────────────


async def test_router_dispatches_known_command() -> None:
    router = _router_with("/status", "ОК")
    assert await router.dispatch("/status") == "ОК"


async def test_router_passes_arguments_and_strips_bot_mention() -> None:
    router = _router_with("/search", "ПОИСК")
    assert await router.dispatch("/search Москва") == "ПОИСК|Москва"
    assert await router.dispatch("/search@logistai_bot Тверь") == "ПОИСК|Тверь"


async def test_router_unknown_command_uses_fallback() -> None:
    router = _router_with("/help", "СПРАВКА")
    router.set_fallback(lambda: "НЕ ЗНАЮ")
    assert await router.dispatch("/nope") == "НЕ ЗНАЮ"


async def test_router_ignores_plain_text() -> None:
    router = _router_with("/help", "СПРАВКА")
    assert await router.dispatch("просто сообщение") is None


def test_router_rejects_duplicates_and_bad_names() -> None:
    router = _router_with("/help", "СПРАВКА")
    with pytest.raises(ValueError, match="уже зарегистрирована"):
        router.register("/help", _router_with("/x", "")._handlers["/x"], description="дубль")
    with pytest.raises(ValueError, match="начинаться"):
        router.register("status", _router_with("/x", "")._handlers["/x"], description="без слэша")


def test_router_lists_commands_for_help_and_botfather() -> None:
    router = TelegramCommandRouter()

    async def noop(_: str) -> str:
        return ""

    router.register("/start", noop, description="что умеет LogistAI")
    router.register("/status", noop, description="состояние")
    assert router.commands() == (
        ("/start", "что умеет LogistAI"),
        ("/status", "состояние"),
    )


# ── Бот: команды, авторизация, callback ──────────────────────────────────────


async def test_bot_replies_to_authorized_command() -> None:
    api = FakeBotApi()
    bot = _bot(api, _router_with("/status", "СТАТУС"))
    api.updates = [TelegramUpdate(update_id=1, chat_id=AUTHORIZED_CHAT, message_text="/status")]

    handled = await bot.poll_once()

    assert handled == 1
    assert api.sent == [(AUTHORIZED_CHAT, "СТАТУС")]


async def test_bot_ignores_foreign_chat_silently(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    api = FakeBotApi()
    bot = _bot(api, _router_with("/status", "СТАТУС"))
    api.updates = [TelegramUpdate(update_id=1, chat_id="999", message_text="/status")]

    await bot.poll_once()

    assert api.sent == []  # чужому чату не отвечаем
    assert "999" not in caplog.text  # chat_id не логируется


async def test_bot_advances_offset() -> None:
    api = FakeBotApi()
    bot = _bot(api, _router_with("/help", "OK"))
    api.updates = [
        TelegramUpdate(update_id=7, chat_id=AUTHORIZED_CHAT, message_text="/help"),
        TelegramUpdate(update_id=8, chat_id=AUTHORIZED_CHAT, message_text="/help"),
    ]
    await bot.poll_once()
    assert bot._offset == 9  # следующий запрос — с нового offset


async def test_bot_callback_details_sends_card() -> None:
    api = FakeBotApi()
    bot = _bot(api)
    api.updates = [
        TelegramUpdate(
            update_id=1,
            chat_id=AUTHORIZED_CHAT,
            callback_id="cb-1",
            callback_data="details:cargo-1",
        )
    ]

    await bot.poll_once()

    assert api.answered and api.answered[0][0] == "cb-1"
    assert api.sent and "Детали cargo-1" in api.sent[0][1]


async def test_bot_callback_ignore_calls_sink() -> None:
    api = FakeBotApi()
    bot = _bot(api)
    api.updates = [
        TelegramUpdate(
            update_id=1,
            chat_id=AUTHORIZED_CHAT,
            callback_id="cb-2",
            callback_data="ignore:cargo-9",
        )
    ]

    await bot.poll_once()

    assert bot.test_ignored == ["cargo-9"]  # type: ignore[attr-defined]
    assert api.answered == [("cb-2", "Груз скрыт")]


async def test_bot_rejects_invalid_callback_data(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    api = FakeBotApi()
    bot = _bot(api)
    api.updates = [
        TelegramUpdate(
            update_id=1,
            chat_id=AUTHORIZED_CHAT,
            callback_id="cb-3",
            callback_data="drop_tables:'; DELETE --",
        )
    ]

    await bot.poll_once()

    assert api.sent == []  # никакого действия
    assert api.answered == [("cb-3", "Кнопка устарела")]
    assert "невалидный callback_data" in caplog.text
    assert "DELETE" not in caplog.text  # содержимое подделки не логируется


async def test_bot_callback_details_for_unknown_cargo() -> None:
    api = FakeBotApi()
    bot = _bot(api)
    api.updates = [
        TelegramUpdate(
            update_id=1,
            chat_id=AUTHORIZED_CHAT,
            callback_id="cb-4",
            callback_data="details:gone-42",
        )
    ]
    await bot.poll_once()
    assert api.sent and "недоступен" in api.sent[0][1]


async def test_bot_start_without_token_is_graceful() -> None:
    bot = TelegramBotService(
        api_factory=lambda token: FakeBotApi(),
        token_provider=lambda: None,
        chat_id_provider=lambda: AUTHORIZED_CHAT,
        router=TelegramCommandRouter(),
    )
    assert await bot.start() is False
    assert bot.running is False


async def test_bot_start_stop_lifecycle() -> None:
    api = FakeBotApi()
    bot = TelegramBotService(
        api_factory=lambda token: api,
        token_provider=lambda: "token-under-test",
        chat_id_provider=lambda: AUTHORIZED_CHAT,
        router=TelegramCommandRouter(),
    )
    assert await bot.start() is True
    assert bot.running
    await bot.stop()
    assert not bot.running and api.closed


# ── Inline keyboard из NotificationAction ────────────────────────────────────


def _cargo_notification(
    actions: tuple[NotificationAction, ...], cargo_id: str = "c-1"
) -> Notification:
    return Notification.create(
        "🚚 Лучший груз найден",
        "Москва → Тверь",
        Severity.SUCCESS,
        category=NotificationCategory.ROUTE,
        actions=actions,
        payload={"cargo_id": cargo_id},
    )


def test_buttons_url_and_callbacks_built() -> None:
    notification = _cargo_notification(
        (
            NotificationAction(id="open", label="Открыть ATI", url="https://ati.su/c/1"),
            NotificationAction(id="details", label="Подробнее"),
            NotificationAction(id="ignore", label="Игнорировать"),
        )
    )
    buttons = _buttons_from_actions(notification)
    assert buttons[0] == TelegramButton(text="Открыть ATI", url="https://ati.su/c/1")
    assert buttons[1].callback_data == "details:c-1"
    assert buttons[2].callback_data == "ignore:c-1"


def test_buttons_skip_callbacks_for_invalid_cargo_id() -> None:
    notification = _cargo_notification(
        (NotificationAction(id="details", label="Подробнее"),),
        cargo_id="плохой id с пробелами",
    )
    assert _buttons_from_actions(notification) == ()  # callback_data не подделать


def test_buttons_skip_unknown_action_ids() -> None:
    notification = _cargo_notification((NotificationAction(id="self_destruct", label="Взорвать"),))
    assert _buttons_from_actions(notification) == ()


# ── Форматтер: категорные шаблоны ────────────────────────────────────────────


def _formatted(category: NotificationCategory, severity: Severity, title: str) -> str:
    return TelegramNotificationFormatter().format(
        Notification.create(title, "тело", severity, category=category)
    )


def test_formatter_best_cargo_and_price_update() -> None:
    assert _formatted(NotificationCategory.ROUTE, Severity.SUCCESS, "Лучший груз").startswith("🚚")
    assert _formatted(NotificationCategory.CARGO, Severity.INFO, "Цена обновилась").startswith("📦")


def test_formatter_monitor_offline_and_restored() -> None:
    offline = _formatted(NotificationCategory.MONITOR, Severity.WARNING, "ATI недоступен")
    restored = _formatted(NotificationCategory.MONITOR, Severity.SUCCESS, "ATI восстановлен")
    assert offline.startswith("⚠️") and restored.startswith("🟢")


def test_formatter_report_and_errors() -> None:
    assert _formatted(NotificationCategory.SYSTEM, Severity.INFO, "Отчёт LogistAI").startswith("📊")
    assert _formatted(NotificationCategory.ERROR, Severity.WARNING, "Ошибка поиска").startswith(
        "🚨"
    )
    assert _formatted(NotificationCategory.SYSTEM, Severity.CRITICAL, "Scheduler упал").startswith(
        "🚨"
    )


def test_formatter_separator_and_escaping() -> None:
    text = TelegramNotificationFormatter().format(
        Notification.create(
            "<script>alert(1)</script>",
            "тело с <b> тегами & символами",
            Severity.INFO,
        )
    )
    assert SEPARATOR in text
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "&lt;b&gt;" in text  # пользовательский HTML экранирован


# ── Бот-ответы (шаблоны команд) ──────────────────────────────────────────────

_NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def test_status_reply_contains_all_fields() -> None:
    text = bot_replies.build_status_reply(
        source_name="ATI.SU",
        health=SourceHealth(status=SourceStatus.ONLINE, last_success=_NOW),
        found_count=542,
        last_search_at=_NOW,
        best_route="Москва → Санкт-Петербург",
        best_score=92,
        scheduler_running=True,
        version="0.1.0-alpha",
    )
    assert "🟢 <b>Online</b>" in text
    assert "Найдено грузов: <b>542</b>" in text
    assert "Москва → Санкт-Петербург" in text and "AI 92" in text
    assert "Scheduler: <b>работает</b>" in text
    assert "0.1.0-alpha" in text


def test_status_reply_offline_marker() -> None:
    text = bot_replies.build_status_reply(
        source_name="ATI.SU",
        health=SourceHealth(status=SourceStatus.FAILED),
        found_count=0,
        last_search_at=None,
        best_route="",
        best_score=0,
        scheduler_running=False,
        version="0.1.0",
    )
    assert "🔴" in text and "ещё не было" in text and "остановлен" in text


def test_report_reply_matches_stage8_analytics() -> None:
    from app.core.models.analytics import MatchingAnalytics

    text = bot_replies.build_report_reply(
        found_count=641,
        statistics=MatchingAnalytics(
            compatible_count=38,
            average_profit=Decimal(82500),
            best_routes=("Москва → Санкт-Петербург",),
        ),
        income=Decimal(310000),
        source_errors={"ati": 2, "ozon": 0},
    )
    assert "Сегодня найдено: <b>641</b>" in text
    assert "Подходящих: <b>38</b>" in text
    assert "82 500 ₽" in text and "310 000 ₽" in text
    assert "Москва → Санкт-Петербург" in text
    assert "ati: <b>2</b>" in text and "ozon" not in text  # нулевые ошибки не шумят


def test_settings_reply_read_only_snapshot() -> None:
    from app.ui.viewmodels import mock_vehicle

    text = bot_replies.build_settings_reply(
        vehicle=mock_vehicle(),
        home_region="Москва",
        minimum_price_per_km=Decimal(100),
        weights=MatchingWeights(),
        enabled_sources=["ATI Москва"],
        channels=["telegram", "macos_native"],
    )
    assert "MAN TGL" in text and "6000 кг" in text
    assert "Регион: <b>Москва</b>" in text
    assert "100 ₽/км" in text
    assert "совместимость <b>30%</b>" in text and "свежесть <b>10%</b>" in text
    assert "ATI Москва" in text and "telegram" in text
    assert "read-only" in text


def test_search_replies_cover_outcomes() -> None:
    found = bot_replies.build_search_result_reply(
        received=5, new_count=4, duplicates=1, best_route="Москва → Тверь", best_score=88
    )
    assert "Получено: <b>5</b>" in found and "🏆" in found and "AI 88" in found
    empty = bot_replies.build_search_result_reply(
        received=5, new_count=0, duplicates=5, best_route="", best_score=0
    )
    assert "продолжаю следить" in empty
    failed = bot_replies.build_search_failed_reply("ATI HTTP 503")
    assert failed.startswith("🚨") and "ATI HTTP 503" in failed


def test_help_and_unknown_replies_list_commands() -> None:
    commands = (("/status", "состояние"), ("/report", "сводка"))
    assert "/status" in bot_replies.build_help_reply(commands)
    unknown = bot_replies.build_unknown_command_reply(commands)
    assert unknown.startswith("🤔") and "/report" in unknown


def test_cargo_details_card() -> None:
    cargo = Cargo(
        id="c-1",
        source_id="ati",
        title="Мебель",
        url="https://ati.su/c/1",
        weight_kg=5000,
        length_cm=500,
        width_cm=200,
        height_cm=220,
        volume_m3=25.0,
        pallet_count=12,
        loading_region="Москва",
        unloading_region="Тверь",
        payment_amount=Decimal(35000),
        distance_km=170.0,
    )
    text = bot_replies.build_cargo_details(cargo)
    assert "Москва → Тверь" in text
    assert "5000 кг" in text and "500×200×220 см" in text
    assert "35 000 ₽" in text and "170 км" in text
    assert 'href="https://ati.su/c/1"' in text


# ── Длинные сообщения и безопасность ─────────────────────────────────────────


def test_split_message_respects_limit_and_lines() -> None:
    lines = [f"строка {i} " + "x" * 90 for i in range(80)]
    text = "\n".join(lines)
    chunks = split_message(text, limit=1000)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "\n".join(chunks).split("\n") == lines  # ни одна строка не потеряна


def test_split_message_short_text_untouched() -> None:
    assert split_message("короткое сообщение") == ("короткое сообщение",)


def test_escape_html_covers_dangerous_characters() -> None:
    assert escape_html('<a href="x">&</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;"


async def test_bot_never_logs_token_or_chat_id(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    api = FakeBotApi()
    bot = _bot(api, _router_with("/status", "СТАТУС"))
    api.updates = [TelegramUpdate(update_id=1, chat_id=AUTHORIZED_CHAT, message_text="/status")]
    await bot.poll_once()
    assert "token-under-test" not in caplog.text
    assert AUTHORIZED_CHAT not in caplog.text
