"""Тексты ответов Telegram-бота (Stage 9.7): /start /help /status /report …

Правило этапа 3 сохраняется: весь внешний вид Telegram-сообщений живёт в
инфраструктуре. Данные сюда приходят примитивами и моделями ядра —
composition root склеивает сервисы с этими чистыми функциями, бот-сервис
получает готовые корутины «команда → HTML».
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from app.core.models.analytics import MatchingAnalytics
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.matching import MatchingWeights
from app.core.models.sources import SourceHealth, SourceStatus
from app.infrastructure.telegram.formatting import TelegramMessageBuilder, escape_html


def _money(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def _time_label(moment: datetime | None) -> str:
    return moment.strftime("%H:%M") if moment is not None else "ещё не было"


def build_start_reply(bot_commands: Sequence[tuple[str, str]]) -> str:
    """/start — приветствие и что бот умеет."""
    builder = (
        TelegramMessageBuilder()
        .title("🚚", "LogistAI на связи")
        .separator()
        .line("Я слежу за грузами, считаю экономику рейсов и присылаю лучшие.")
        .line()
        .line("Команды:")
    )
    for command, description in bot_commands:
        builder.raw_html(f"{escape_html(command)} — {escape_html(description)}")
    return builder.build()


def build_help_reply(bot_commands: Sequence[tuple[str, str]]) -> str:
    """/help — список команд."""
    builder = TelegramMessageBuilder().title("ℹ️", "Команды LogistAI").separator()
    for command, description in bot_commands:
        builder.raw_html(f"<b>{escape_html(command)}</b> — {escape_html(description)}")
    return builder.build()


def build_status_reply(
    *,
    source_name: str,
    health: SourceHealth,
    found_count: int,
    last_search_at: datetime | None,
    best_route: str,
    best_score: int,
    scheduler_running: bool,
    version: str,
) -> str:
    """/status — состояние платформы одним сообщением."""
    online = health.status is SourceStatus.ONLINE
    builder = (
        TelegramMessageBuilder()
        .title("📡", "Статус LogistAI")
        .separator()
        .raw_html(
            f"{escape_html(source_name)}: "
            + ("🟢 <b>Online</b>" if online else f"🔴 <b>{escape_html(health.status.value)}</b>")
        )
        .key_value("Последняя синхронизация", _time_label(health.last_success))
        .key_value("Последний поиск", _time_label(last_search_at))
        .key_value("Найдено грузов", str(found_count))
    )
    if best_route:
        builder.raw_html(f"Лучший груз: <b>{escape_html(best_route)}</b> · AI {best_score}")
    builder.key_value("Scheduler", "работает" if scheduler_running else "остановлен")
    builder.key_value("Версия", version)
    return builder.build()


def build_report_reply(
    *,
    found_count: int,
    statistics: MatchingAnalytics,
    income: Decimal,
    source_errors: Mapping[str, int],
) -> str:
    """/report — дневная сводка (аналитика Stage 8)."""
    builder = (
        TelegramMessageBuilder()
        .title("📊", "Отчёт LogistAI")
        .separator()
        .key_value("🚚 Сегодня найдено", str(found_count))
        .key_value("✅ Подходящих", str(statistics.compatible_count))
    )
    if statistics.average_profit > 0:
        builder.key_value("💰 Средняя прибыль", _money(statistics.average_profit))
    if income > 0:
        builder.key_value("📈 Доход (сумма лучших)", _money(income))
    if statistics.best_routes:
        builder.key_value("⭐ Лучший маршрут", statistics.best_routes[0])
    errors = {source: count for source, count in source_errors.items() if count}
    if errors:
        builder.line().line("Ошибки источников:")
        for source, count in errors.items():
            builder.key_value(f"  {source}", str(count))
    return builder.build()


def build_settings_reply(
    *,
    vehicle: VehicleProfile | None,
    home_region: str,
    minimum_price_per_km: Decimal | None,
    weights: MatchingWeights,
    enabled_sources: Sequence[str],
    channels: Sequence[str],
) -> str:
    """/settings — текущая конфигурация (read-only)."""
    builder = TelegramMessageBuilder().title("⚙️", "Настройки LogistAI").separator()
    if vehicle is not None:
        builder.key_value("Машина", vehicle.name)
        builder.key_value("Грузоподъёмность", f"{vehicle.cargo_capacity_kg} кг")
    else:
        builder.line("Машина: не настроена")
    builder.key_value("Регион", home_region if home_region else "не задан")
    builder.key_value(
        "Мин. ставка",
        f"{minimum_price_per_km:.0f} ₽/км" if minimum_price_per_km is not None else "не задана",
    )
    builder.raw_html(
        f"AI Score: совместимость <b>{weights.compatibility:.0%}</b>"
        f" · прибыль <b>{weights.profit:.0%}</b>"
        f" · маршрут <b>{weights.route:.0%}</b>"
        f" · предпочтения <b>{weights.preferences:.0%}</b>"
        f" · свежесть <b>{weights.freshness:.0%}</b>"
    )
    builder.key_value("Источники", ", ".join(enabled_sources) if enabled_sources else "не включены")
    builder.key_value("Каналы уведомлений", ", ".join(channels) if channels else "нет")
    builder.line().line("Изменение настроек — в приложении LogistAI (read-only в боте).")
    return builder.build()


def build_search_started_reply() -> str:
    """/search — подтверждение запуска."""
    return (
        TelegramMessageBuilder()
        .title("🔍", "Поиск запущен")
        .line("Опрашиваю источники и подбираю лучший груз…")
        .build()
    )


def build_search_result_reply(
    *,
    received: int,
    new_count: int,
    duplicates: int,
    best_route: str,
    best_score: int,
) -> str:
    """/search — итог: сколько получено и найден ли лучший."""
    builder = (
        TelegramMessageBuilder()
        .title("🔍", "Поиск завершён")
        .separator()
        .key_value("Получено", str(received))
        .key_value("Новых", str(new_count))
        .key_value("Дубликатов", str(duplicates))
    )
    if best_route:
        builder.line().raw_html(
            f"🏆 Лучший груз: <b>{escape_html(best_route)}</b> · AI {best_score}"
        )
        builder.line("Карточка с кнопками придёт отдельным сообщением.")
    else:
        builder.line().line("Новых подходящих грузов нет — продолжаю следить.")
    return builder.build()


def build_search_failed_reply(error: str) -> str:
    """/search — источник не ответил."""
    return (
        TelegramMessageBuilder()
        .title("🚨", "Поиск не удался")
        .line(error)
        .line("Попробуйте позже или проверьте /status.")
        .build()
    )


def build_unknown_command_reply(bot_commands: Sequence[tuple[str, str]]) -> str:
    """Неизвестная команда — подсказка."""
    builder = TelegramMessageBuilder().title("🤔", "Не знаю такой команды").separator()
    for command, description in bot_commands:
        builder.raw_html(f"{escape_html(command)} — {escape_html(description)}")
    return builder.build()


def build_cargo_details(cargo: Cargo) -> str:
    """Кнопка «Подробнее»: полная карточка груза."""
    route = " → ".join(p for p in (cargo.loading_region, cargo.unloading_region) if p)
    builder = TelegramMessageBuilder().title("📦", route if route else "Груз").separator()
    if cargo.title:
        builder.key_value("Груз", cargo.title)
    if cargo.weight_kg is not None:
        builder.key_value("Вес", f"{cargo.weight_kg} кг")
    if cargo.length_cm is not None and cargo.width_cm is not None and cargo.height_cm is not None:
        builder.key_value("Габариты", f"{cargo.length_cm}×{cargo.width_cm}×{cargo.height_cm} см")
    if cargo.volume_m3 is not None:
        builder.key_value("Объём", f"{cargo.volume_m3:g} м³")
    if cargo.pallet_count is not None:
        builder.key_value("Паллеты", str(cargo.pallet_count))
    if cargo.payment_amount is not None:
        builder.key_value("Цена", _money(cargo.payment_amount))
    if cargo.distance_km is not None:
        builder.key_value("Расстояние", f"{cargo.distance_km:.0f} км")
    if cargo.url:
        builder.line().link("Открыть объявление", cargo.url)
    return builder.build()
