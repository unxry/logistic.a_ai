"""Типизированная модель настроек приложения.

Секреты (Bot Token) здесь НЕ хранятся — только в SecretStore (ADR-0008).
Модель неизменяемая: обновление — через ``dataclasses.replace``.
Дефолты синхронизированы с ``config/defaults.json`` (охраняется тестом).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.matching import MatchingWeights
from app.core.models.routes import RouteCostPolicy

SCHEMA_VERSION = 2


class Theme(Enum):
    """Тема оформления."""

    DARK = "dark"
    LIGHT = "light"


@dataclass(frozen=True, slots=True)
class UISettings:
    """Настройки интерфейса."""

    theme: Theme = Theme.DARK
    autostart: bool = False


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    """Настройки Telegram (токен — в SecretStore, не здесь)."""

    enabled: bool = True
    chat_id: str = ""


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    """Настройки уведомлений: какие каналы включены (строковые id)."""

    enabled_channels: tuple[str, ...] = ("telegram", "macos_native")


@dataclass(frozen=True, slots=True)
class HistorySettings:
    """Настройки журнала событий."""

    retention_days: int = 90


@dataclass(frozen=True, slots=True)
class SchedulerSettings:
    """Настройки планировщика фоновых задач."""

    telegram_health_check_minutes: int = 5


@dataclass(frozen=True, slots=True)
class MonitoringSettings:
    """Настройки мониторинга источников (задел под v0.2)."""

    refresh_interval_seconds: int = 60


@dataclass(frozen=True, slots=True)
class VehicleSettings:
    """Транспорт пользователя: профили и активный профиль.

    Профили хранятся в настройках (JSON), пока не появится полноценный
    репозиторий в SQLite — этого достаточно для единиц машин (ADR-0010).
    """

    profiles: tuple[VehicleProfile, ...] = ()
    active_profile_id: str | None = None

    def active_profile(self) -> VehicleProfile | None:
        """Активный профиль; ``None``, если не задан или id не найден."""
        for profile in self.profiles:
            if profile.id == self.active_profile_id:
                return profile
        return None


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Все настройки приложения.

    ``routing`` и ``matching`` (Stage 8.5) — доменные модели ядра напрямую:
    тарифы экономики рейса и веса интеллектуального подбора.
    """

    schema_version: int = SCHEMA_VERSION
    ui: UISettings = field(default_factory=UISettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    history: HistorySettings = field(default_factory=HistorySettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)
    vehicle: VehicleSettings = field(default_factory=VehicleSettings)
    routing: RouteCostPolicy = field(default_factory=RouteCostPolicy)
    matching: MatchingWeights = field(default_factory=MatchingWeights)
