"""Порты (typing.Protocol) — контракты ядра, публичный каталог."""

from app.core.ports.autostart import AutostartManager
from app.core.ports.cargo_compatibility import CargoCompatibilityChecker
from app.core.ports.cargo_repository import CargoRepository
from app.core.ports.cargo_source import CargoSource
from app.core.ports.event_publisher import EventPublisher
from app.core.ports.geocoding_provider import GeocodingProvider
from app.core.ports.history_repository import HistoryRepository
from app.core.ports.job import Job
from app.core.ports.log_buffer import LogBuffer
from app.core.ports.matching_repository import MatchingRepository
from app.core.ports.notification_channel import NotificationChannel
from app.core.ports.notification_formatter import NotificationFormatter
from app.core.ports.notification_history_repository import NotificationHistoryRepository
from app.core.ports.notification_sender import NotificationSender
from app.core.ports.path_provider import PathProvider
from app.core.ports.plugin_extensions import PluginExtensions
from app.core.ports.route_cache_repository import RouteCacheRepository
from app.core.ports.route_provider import RouteProvider
from app.core.ports.secret_store import SecretStore
from app.core.ports.settings_repository import SettingsRepository
from app.core.ports.source_configuration import SourceConfigurationRepository
from app.core.ports.source_credentials import SourceCredentialProvider
from app.core.ports.telegram_api import TelegramApi, TelegramApiFactory

__all__ = [
    "AutostartManager",
    "CargoCompatibilityChecker",
    "CargoRepository",
    "CargoSource",
    "EventPublisher",
    "GeocodingProvider",
    "HistoryRepository",
    "Job",
    "LogBuffer",
    "MatchingRepository",
    "NotificationChannel",
    "NotificationFormatter",
    "NotificationHistoryRepository",
    "NotificationSender",
    "PathProvider",
    "PluginExtensions",
    "RouteCacheRepository",
    "RouteProvider",
    "SecretStore",
    "SettingsRepository",
    "SourceConfigurationRepository",
    "SourceCredentialProvider",
    "TelegramApi",
    "TelegramApiFactory",
]
