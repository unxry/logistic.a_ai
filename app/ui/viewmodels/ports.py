"""Порты presentation-слоя (Stage 8.6).

ViewModel'и не знают ни Qt, ни конкретных сервисов — только эти протоколы
и модели ядра (контракт закреплён import-linter). Живая реализация —
``DashboardDataService`` (services/presentation) — удовлетворяет протокол
СТРУКТУРНО, не импортируя этот модуль; для разработки UI без домена есть
``MockDashboardDataProvider``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from app.core.commands import Command
from app.core.events import Event
from app.core.models.analytics import MatchingAnalytics
from app.core.models.connection import ConnectionState
from app.core.models.history import HistoryEntry
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.notification_history import NotificationHistoryEntry
from app.core.models.sources import SourceHealth


class EventStream(Protocol):
    """Подписка и публикация событий (структурно совместим с EventBus)."""

    def subscribe[E: Event](self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Подписать обработчик на тип события."""
        ...

    def unsubscribe[E: Event](self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Отписать обработчик."""
        ...

    def publish(self, event: Event) -> None:
        """Опубликовать событие."""
        ...


class CommandDispatcher(Protocol):
    """Структурный порт CommandBus для UI: только dispatch, без зависимости от buses."""

    async def dispatch[R](self, command: Command[R]) -> R:
        """Выполнить команду изменения состояния."""
        ...


class DashboardDataProvider(Protocol):
    """Источник данных дашборда (read-model поверх сервисов платформы).

    Синхронные методы — снапшоты состояния в памяти; асинхронные — походы
    в хранилище (SQLite), их зовёт ``DashboardViewModel.refresh()``.
    """

    def telegram_state(self) -> ConnectionState:
        """Текущее состояние Telegram-подключения."""
        ...

    def active_vehicle(self) -> VehicleProfile | None:
        """Активный профиль транспорта; ``None`` — не настроен."""
        ...

    def sources_health(self) -> Mapping[str, SourceHealth]:
        """Здоровье источников по id."""
        ...

    def source_names(self) -> Mapping[str, str]:
        """Человекочитаемые имена источников по id."""
        ...

    def cargo_counts(self) -> Mapping[str, int]:
        """Сколько грузов получено от каждого источника."""
        ...

    async def matching_statistics(self) -> MatchingAnalytics:
        """Сводная статистика подбора (из хранилища решений)."""
        ...

    async def recent_events(self, limit: int) -> Sequence[HistoryEntry]:
        """Последние записи журнала (новые первыми)."""
        ...

    async def favorite_cargos(self, limit: int) -> Sequence[Cargo]:
        """Сохранённые пользователем избранные грузы."""
        ...

    async def notification_history(self, limit: int) -> Sequence[NotificationHistoryEntry]:
        """История уведомлений для отдельного Timeline."""
        ...
