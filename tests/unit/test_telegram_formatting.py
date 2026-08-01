"""Тесты форматирования Telegram: экранирование, Builder, Formatter."""

from __future__ import annotations

from app.core.models.notification import Notification
from app.core.models.severity import Severity
from app.infrastructure.telegram.formatting import (
    TelegramMessageBuilder,
    TelegramNotificationFormatter,
    escape_html,
)


def test_escape_html_all_special_chars() -> None:
    assert escape_html('<b> & "x" >') == "&lt;b&gt; &amp; &quot;x&quot; &gt;"


def test_escape_html_ampersand_first() -> None:
    # уже экранированная сущность экранируется честно, а не ломается
    assert escape_html("&lt;") == "&amp;lt;"


def test_builder_composes_message() -> None:
    message = (
        TelegramMessageBuilder()
        .title("🚛", "Новый груз")
        .line()
        .key_value("Маршрут", "Москва → Казань")
        .key_value("Оплата", "195 000 ₽")
        .link("Открыть", "https://example.com/cargo/1")
        .build()
    )
    assert message.splitlines()[0] == "🚛 <b>Новый груз</b>"
    assert "Маршрут: <b>Москва → Казань</b>" in message
    assert '<a href="https://example.com/cargo/1">Открыть</a>' in message


def test_builder_escapes_user_data_everywhere() -> None:
    message = (
        TelegramMessageBuilder()
        .title("⚠️", "<script>")
        .line('a & "b"')
        .key_value("<k>", "<v>")
        .link("<текст>", "https://example.com/?a=1&b=2")
        .build()
    )
    assert "<script>" not in message
    assert "&lt;script&gt;" in message
    assert "a &amp; &quot;b&quot;" in message
    assert "&lt;k&gt;: <b>&lt;v&gt;</b>" in message
    assert 'href="https://example.com/?a=1&amp;b=2"' in message


def test_formatter_format_notification() -> None:
    formatter = TelegramNotificationFormatter()
    text = formatter.format(
        Notification.create("Груз <найден>", "Москва & Казань", Severity.CRITICAL)
    )
    assert text.startswith("🚨 <b>Груз &lt;найден&gt;</b>")
    assert "Москва &amp; Казань" in text


def test_formatter_test_message() -> None:
    text = TelegramNotificationFormatter().format_test_message()
    assert "LogistAI" in text
    assert "<b>" in text  # HTML-разметка на месте


def test_production_formatter_never_contains_split_test_text() -> None:
    text = TelegramNotificationFormatter().format(
        Notification.create("Проверка", "Telegram подключён", Severity.INFO)
    )

    assert "Проверка split" not in text
