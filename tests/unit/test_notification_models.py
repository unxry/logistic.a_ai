"""Тесты расширенной модели уведомлений, Builder и отчётов."""

from __future__ import annotations

import pytest

from app.core.models.notification import (
    DeliveryReport,
    DeliveryResult,
    Notification,
    NotificationCategory,
    NotificationContext,
)
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.severity import Severity
from app.infrastructure.telegram.formatting import TelegramNotificationFormatter


def test_notification_defaults() -> None:
    n = Notification.create("Заголовок", "Тело")
    assert n.category is NotificationCategory.SYSTEM
    assert n.actions == ()
    assert dict(n.payload) == {}
    assert n.context.source == "system"
    assert len(n.trace_id) == 32  # UUID сквозной корреляции


def test_context_carries_trace_id() -> None:
    context = NotificationContext(source="monitor", module="ati", trace_id="trace-1")
    n = Notification.create("З", "т", context=context)
    assert n.trace_id == "trace-1"
    assert n.context.module == "ati"


def test_builder_full_notification() -> None:
    n = (
        NotificationBuilder()
        .title("Новый груз")
        .body("Москва → Казань")
        .severity(Severity.SUCCESS)
        .category(NotificationCategory.CARGO)
        .channel("telegram")
        .action("Открыть ATI", "https://ati.su/cargo/1")
        .payload_item("cargo_id", "c-42")
        .source("monitor")
        .module("ati")
        .trace_id("t-123")
        .build()
    )
    assert n.title == "Новый груз"
    assert n.category is NotificationCategory.CARGO
    assert n.channels == ("telegram",)
    assert n.actions[0].label == "Открыть ATI"
    assert n.payload["cargo_id"] == "c-42"
    assert n.trace_id == "t-123"
    assert n.context.source == "monitor"


def test_builder_requires_title() -> None:
    with pytest.raises(ValueError, match="заголовок"):
        NotificationBuilder().body("без заголовка").build()


def test_report_channel_properties() -> None:
    report = DeliveryReport(
        notification_id="n1",
        results=(
            DeliveryResult(channel_id="telegram", ok=True, duration_ms=12),
            DeliveryResult(channel_id="macos_native", ok=False, error="нет osascript"),
        ),
        trace_id="t-1",
        duration_ms=15,
    )
    assert report.successful_channels == ("telegram",)
    assert report.failed_channels == ("macos_native",)
    assert report.delivered_any and not report.all_ok
    assert report.trace_id == "t-1"


def test_telegram_formatter_keeps_actions_out_of_text() -> None:
    """Stage 9.7: действия уходят inline-кнопками, в текст не попадают."""
    n = (
        NotificationBuilder()
        .title("Новый груз")
        .body("Москва → Казань")
        .action("Открыть ATI", "https://ati.su/c/1")
        .action("Скрыть")
        .build()
    )
    text = TelegramNotificationFormatter().format(n)
    assert "Москва → Казань" in text
    assert "ati.su" not in text  # ссылка — в клавиатуре, не в тексте
    assert "Скрыть" not in text
