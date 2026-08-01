"""DashboardDataService — живой read-model дашборда (Stage 8.6).

Собирает данные для DashboardViewModel из сервисов платформы. СТРУКТУРНО
удовлетворяет порт ``app.ui.viewmodels.ports.DashboardDataProvider``, не
импортируя его (services не знают ui — контракт import-linter); соответствие
проверяет mypy в composition root.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.models.analytics import MatchingAnalytics
from app.core.models.cargo_workflow import CargoWorkflowState
from app.core.models.connection import ConnectionState
from app.core.models.history import HistoryEntry
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.notification_history import NotificationHistoryEntry
from app.core.models.sources import SourceHealth
from app.core.ports import (
    CargoRepository,
    HistoryRepository,
    MatchingRepository,
    NotificationHistoryRepository,
)
from app.services.monitoring import AnalyticsCollector
from app.services.settings_service import SettingsService
from app.services.sources import SourceRegistry, SourceRuntime
from app.services.telegram import TelegramService


class DashboardDataService:
    """Данные дашборда поверх готовых сервисов (только чтение)."""

    def __init__(
        self,
        *,
        telegram: TelegramService,
        settings: SettingsService,
        registry: SourceRegistry,
        runtime: SourceRuntime,
        collector: AnalyticsCollector,
        matching_repository: MatchingRepository,
        history: HistoryRepository,
        cargos: CargoRepository,
        notification_history: NotificationHistoryRepository,
    ) -> None:
        self._telegram = telegram
        self._settings = settings
        self._registry = registry
        self._runtime = runtime
        self._collector = collector
        self._matching = matching_repository
        self._history = history
        self._cargos = cargos
        self._notification_history = notification_history

    def telegram_state(self) -> ConnectionState:
        """Текущее состояние Telegram-подключения."""
        return self._telegram.state

    def active_vehicle(self) -> VehicleProfile | None:
        """Активный профиль транспорта из настроек."""
        return self._settings.current.vehicle.active_profile()

    def sources_health(self) -> Mapping[str, SourceHealth]:
        """Здоровье всех зарегистрированных источников."""
        return {source_id: self._runtime.health(source_id) for source_id in self._registry.ids()}

    def source_names(self) -> Mapping[str, str]:
        """Человекочитаемые имена источников."""
        return {
            source_id: self._registry.get(source_id).spec.name for source_id in self._registry.ids()
        }

    def cargo_counts(self) -> Mapping[str, int]:
        """Грузов получено от каждого источника (счётчики коллектора)."""
        return dict(self._collector.cargo_received)

    async def matching_statistics(self) -> MatchingAnalytics:
        """Сводная статистика подбора из хранилища решений."""
        return await self._matching.get_statistics()

    async def recent_events(self, limit: int) -> Sequence[HistoryEntry]:
        """Последние записи журнала."""
        return await self._history.query(limit=limit)

    async def favorite_cargos(self, limit: int) -> Sequence[Cargo]:
        """Избранные грузы из постоянного хранилища."""
        return await self._cargos.list_by_state(CargoWorkflowState.FAVORITE, limit=limit)

    async def notification_history(self, limit: int) -> Sequence[NotificationHistoryEntry]:
        """История уведомлений."""
        return await self._notification_history.query(limit=limit)
