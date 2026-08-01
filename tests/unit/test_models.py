"""Тесты доменных моделей: фабрики, отчёты, синхронизация дефолтов с JSON."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.notification import DeliveryReport, DeliveryResult, Notification
from app.core.models.settings import AppSettings
from app.core.models.severity import Severity

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_notification_create_fills_id_and_time() -> None:
    first = Notification.create("Заголовок", "Текст")
    second = Notification.create("Заголовок", "Текст")
    assert first.id != second.id
    assert first.created_at.tzinfo is not None
    assert first.severity is Severity.INFO
    assert first.channels is None  # None = все включённые каналы


def test_history_entry_create() -> None:
    entry = HistoryEntry.create(HistoryKind.SYSTEM_EVENT, Severity.INFO, "Запуск", source="app")
    assert entry.id
    assert entry.occurred_at.tzinfo is not None
    assert entry.kind is HistoryKind.SYSTEM_EVENT
    assert entry.details == ""


def test_delivery_report_flags() -> None:
    ok = DeliveryResult(channel_id="telegram", ok=True)
    fail = DeliveryResult(channel_id="macos_native", ok=False, error="нет прав")

    full = DeliveryReport(notification_id="n1", results=(ok,))
    partial = DeliveryReport(notification_id="n2", results=(ok, fail))
    empty = DeliveryReport(notification_id="n3", results=())

    assert full.all_ok and full.delivered_any
    assert not partial.all_ok and partial.delivered_any
    assert partial.failed() == (fail,)
    assert not empty.all_ok and not empty.delivered_any


def test_defaults_json_matches_settings_model() -> None:
    """config/defaults.json и AppSettings() не должны расходиться."""
    data = json.loads((PROJECT_ROOT / "config" / "defaults.json").read_text(encoding="utf-8"))
    settings = AppSettings()

    assert data["schema_version"] == settings.schema_version
    assert data["ui"]["theme"] == settings.ui.theme.value
    assert data["ui"]["autostart"] == settings.ui.autostart
    assert data["telegram"]["enabled"] == settings.telegram.enabled
    assert data["telegram"]["chat_id"] == settings.telegram.chat_id
    assert (
        tuple(data["notifications"]["enabled_channels"]) == settings.notifications.enabled_channels
    )
    assert data["history"]["retention_days"] == settings.history.retention_days
    assert (
        data["scheduler"]["telegram_health_check_minutes"]
        == settings.scheduler.telegram_health_check_minutes
    )
    assert (
        data["monitoring"]["refresh_interval_seconds"]
        == settings.monitoring.refresh_interval_seconds
    )
    assert data["vehicle"]["active_profile_id"] == settings.vehicle.active_profile_id
    routing = data["routing"]
    assert routing["fuel_consumption_l_per_100km"] == settings.routing.fuel_consumption_l_per_100km
    assert routing["fuel_price_per_liter"] == settings.routing.fuel_price_per_liter
    assert routing["toll_cost_per_km"] == settings.routing.toll_cost_per_km
    assert routing["maintenance_cost_per_km"] == settings.routing.maintenance_cost_per_km
    assert routing["driver_cost_per_hour"] == settings.routing.driver_cost_per_hour
    assert routing["average_speed_kmh"] == settings.routing.average_speed_kmh
    matching = data["matching"]
    assert matching["compatibility"] == settings.matching.compatibility
    assert matching["profit"] == settings.matching.profit
    assert matching["route"] == settings.matching.route
    assert matching["preferences"] == settings.matching.preferences
    assert matching["freshness"] == settings.matching.freshness
    assert list(data["vehicle"]["profiles"]) == list(settings.vehicle.profiles)
