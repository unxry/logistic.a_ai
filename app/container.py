"""Контейнер зависимостей приложения.

Единственное место, где живут «синглтоны» (никаких глобальных переменных).
Заполняется в ``app.bootstrap.build_container``.

Контейнер — деталь composition root: слои приложения (ui, services, ...)
его НЕ импортируют; каждый компонент получает через конструктор только то,
что ему нужно (Interface Segregation).
"""

from dataclasses import dataclass

from app.buses import CommandBus, EventBus
from app.core.models.build_info import BuildInfo
from app.core.ports import (
    CargoRepository,
    HistoryRepository,
    LogBuffer,
    MatchingRepository,
    NotificationHistoryRepository,
    PathProvider,
)
from app.infrastructure.sources.ati import AtiClient
from app.infrastructure.storage.database import Database
from app.services.matching import IntelligentMatchingService
from app.services.monitoring import AnalyticsCollector, SourceHealthMonitor
from app.services.notifications import NotificationService
from app.services.routes import RouteService
from app.services.scheduler import JobRegistry, SchedulerRuntime
from app.services.search import CargoMatchingService, RecommendationPipeline
from app.services.settings_service import SettingsService
from app.services.sources import SourceRegistry, SourceRuntime
from app.services.telegram import TelegramBotService, TelegramService
from app.ui.viewmodels import DashboardViewModel


@dataclass(slots=True)
class AppContainer:
    """Все собранные зависимости приложения (один экземпляр на процесс)."""

    build_info: BuildInfo
    event_bus: EventBus
    command_bus: CommandBus
    path_provider: PathProvider
    settings_service: SettingsService
    telegram_service: TelegramService
    telegram_bot: TelegramBotService
    notification_service: NotificationService
    job_registry: JobRegistry
    scheduler: SchedulerRuntime
    source_registry: SourceRegistry
    source_runtime: SourceRuntime
    cargo_repository: CargoRepository
    matching_service: CargoMatchingService
    recommendation_pipeline: RecommendationPipeline
    ati_client: AtiClient
    route_service: RouteService
    intelligent_matcher: IntelligentMatchingService
    matching_repository: MatchingRepository
    analytics_collector: AnalyticsCollector
    health_monitor: SourceHealthMonitor
    dashboard_viewmodel: DashboardViewModel
    history_repository: HistoryRepository
    notification_history_repository: NotificationHistoryRepository
    database: Database
    log_buffer: LogBuffer
