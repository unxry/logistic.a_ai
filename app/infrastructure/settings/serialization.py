"""Сериализация AppSettings ↔ JSON-словарь.

Парсинг толерантный: отсутствующие ключи и мусорные значения заменяются
дефолтами модели, битые профили транспорта пропускаются — настройки не должны
«ронять» приложение. Секретов здесь нет по построению (они в SecretStore).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.matching import MatchingWeights
from app.core.models.routes import RouteCostPolicy
from app.core.models.settings import (
    SCHEMA_VERSION,
    AppSettings,
    HistorySettings,
    MonitoringSettings,
    NotificationSettings,
    SchedulerSettings,
    TelegramSettings,
    Theme,
    UISettings,
    VehicleSettings,
)


def settings_to_dict(settings: AppSettings) -> dict[str, Any]:
    """AppSettings → словарь для JSON (порядок ключей — как в defaults.json)."""
    return {
        "schema_version": settings.schema_version,
        "ui": {
            "theme": settings.ui.theme.value,
            "autostart": settings.ui.autostart,
        },
        "telegram": {
            "enabled": settings.telegram.enabled,
            "chat_id": settings.telegram.chat_id,
        },
        "notifications": {
            "enabled_channels": list(settings.notifications.enabled_channels),
        },
        "history": {
            "retention_days": settings.history.retention_days,
        },
        "scheduler": {
            "telegram_health_check_minutes": settings.scheduler.telegram_health_check_minutes,
        },
        "monitoring": {
            "refresh_interval_seconds": settings.monitoring.refresh_interval_seconds,
        },
        "vehicle": {
            "profiles": [_profile_to_dict(p) for p in settings.vehicle.profiles],
            "active_profile_id": settings.vehicle.active_profile_id,
        },
        "routing": {
            "fuel_consumption_l_per_100km": float(settings.routing.fuel_consumption_l_per_100km),
            "fuel_price_per_liter": float(settings.routing.fuel_price_per_liter),
            "toll_cost_per_km": float(settings.routing.toll_cost_per_km),
            "maintenance_cost_per_km": float(settings.routing.maintenance_cost_per_km),
            "driver_cost_per_hour": float(settings.routing.driver_cost_per_hour),
            "average_speed_kmh": settings.routing.average_speed_kmh,
        },
        "matching": {
            "compatibility": settings.matching.compatibility,
            "profit": settings.matching.profit,
            "route": settings.matching.route,
            "preferences": settings.matching.preferences,
            "freshness": settings.matching.freshness,
        },
    }


def settings_from_dict(data: Mapping[str, Any]) -> AppSettings:
    """Словарь из JSON → AppSettings (после миграций до текущей схемы)."""
    base = AppSettings()
    ui = _section(data, "ui")
    telegram = _section(data, "telegram")
    notifications = _section(data, "notifications")
    history = _section(data, "history")
    scheduler = _section(data, "scheduler")
    monitoring = _section(data, "monitoring")
    vehicle = _section(data, "vehicle")
    routing = _section(data, "routing")
    matching = _section(data, "matching")

    return AppSettings(
        schema_version=SCHEMA_VERSION,
        ui=UISettings(
            theme=_enum(Theme, ui.get("theme"), base.ui.theme),
            autostart=_bool(ui.get("autostart"), base.ui.autostart),
        ),
        telegram=TelegramSettings(
            enabled=_bool(telegram.get("enabled"), base.telegram.enabled),
            chat_id=_str(telegram.get("chat_id"), base.telegram.chat_id),
        ),
        notifications=NotificationSettings(
            enabled_channels=_str_tuple(
                notifications.get("enabled_channels"),
                base.notifications.enabled_channels,
            ),
        ),
        history=HistorySettings(
            retention_days=_int(history.get("retention_days"), base.history.retention_days),
        ),
        scheduler=SchedulerSettings(
            telegram_health_check_minutes=_int(
                scheduler.get("telegram_health_check_minutes"),
                base.scheduler.telegram_health_check_minutes,
            ),
        ),
        monitoring=MonitoringSettings(
            refresh_interval_seconds=_int(
                monitoring.get("refresh_interval_seconds"),
                base.monitoring.refresh_interval_seconds,
            ),
        ),
        vehicle=VehicleSettings(
            profiles=_profiles(vehicle.get("profiles")),
            active_profile_id=_opt_str(vehicle.get("active_profile_id")),
        ),
        routing=_routing(routing, base.routing),
        matching=_matching(matching, base.matching),
    )


def _routing(section: Mapping[str, Any], default: RouteCostPolicy) -> RouteCostPolicy:
    """Тарифы экономики рейса; мусорные значения → дефолты (валидация модели)."""
    try:
        return RouteCostPolicy(
            fuel_consumption_l_per_100km=_decimal(
                section.get("fuel_consumption_l_per_100km"),
                default.fuel_consumption_l_per_100km,
            ),
            fuel_price_per_liter=_decimal(
                section.get("fuel_price_per_liter"), default.fuel_price_per_liter
            ),
            toll_cost_per_km=_decimal(section.get("toll_cost_per_km"), default.toll_cost_per_km),
            maintenance_cost_per_km=_decimal(
                section.get("maintenance_cost_per_km"), default.maintenance_cost_per_km
            ),
            driver_cost_per_hour=_decimal(
                section.get("driver_cost_per_hour"), default.driver_cost_per_hour
            ),
            average_speed_kmh=_float(section.get("average_speed_kmh"), default.average_speed_kmh),
        )
    except ValueError:
        return default


def _matching(section: Mapping[str, Any], default: MatchingWeights) -> MatchingWeights:
    """Веса подбора; некорректная сумма или мусор → дефолты (валидация модели)."""
    try:
        return MatchingWeights(
            compatibility=_float(section.get("compatibility"), default.compatibility),
            profit=_float(section.get("profit"), default.profit),
            route=_float(section.get("route"), default.route),
            preferences=_float(section.get("preferences"), default.preferences),
            freshness=_float(section.get("freshness"), default.freshness),
        )
    except ValueError:
        return default


def _profile_to_dict(profile: VehicleProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "vehicle_type": profile.vehicle_type.value,
        "body_type": profile.body_type.value,
        "cargo_capacity_kg": profile.cargo_capacity_kg,
        "length_cm": profile.length_cm,
        "width_cm": profile.width_cm,
        "height_cm": profile.height_cm,
        "volume_m3": profile.volume_m3,
        "pallet_capacity": profile.pallet_capacity,
        "max_weight_kg": profile.max_weight_kg,
        "allowed_regions": list(profile.allowed_regions),
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def _profile_from_dict(item: Mapping[str, Any]) -> VehicleProfile:
    max_weight = item.get("max_weight_kg")
    return VehicleProfile(
        id=str(item["id"]),
        name=str(item["name"]),
        vehicle_type=VehicleType(item["vehicle_type"]),
        body_type=BodyType(item["body_type"]),
        cargo_capacity_kg=int(item["cargo_capacity_kg"]),
        length_cm=int(item["length_cm"]),
        width_cm=int(item["width_cm"]),
        height_cm=int(item["height_cm"]),
        volume_m3=float(item["volume_m3"]),
        pallet_capacity=int(item["pallet_capacity"]),
        created_at=datetime.fromisoformat(str(item["created_at"])),
        updated_at=datetime.fromisoformat(str(item["updated_at"])),
        max_weight_kg=int(max_weight) if max_weight is not None else None,
        allowed_regions=tuple(str(r) for r in item.get("allowed_regions", ())),
    )


def _profiles(value: Any) -> tuple[VehicleProfile, ...]:
    """Разобрать профили; битые записи пропускаются (толерантность)."""
    if not isinstance(value, list):
        return ()
    result: list[VehicleProfile] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        try:
            result.append(_profile_from_dict(item))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(result)


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


def _enum[E: Enum](enum_cls: type[E], value: Any, default: E) -> E:
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _float(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _decimal(value: Any, default: Decimal) -> Decimal:
    """Деньги из JSON: число или строка; мусор — дефолт."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return default


def _str(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    return tuple(str(item) for item in value)
