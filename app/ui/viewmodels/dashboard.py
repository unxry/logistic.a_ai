"""DashboardViewModel — презентер дашборда (Stage 8.6, без Qt).

Слушает доменные события (Telegram, здоровье источников, приход грузов),
держит презентационное состояние и публикует три UI-события:
DashboardUpdated, CargoRecommendationChanged, SourceStatusChanged.
Данные тянет через порт DashboardDataProvider — живой адаптер собирается
в bootstrap, для разработки UI есть MockDashboardDataProvider.

Асинхронный только ``refresh()`` (походы в хранилище); обработчики событий
синхронны и обновляют состояние в памяти — петля qasync (Stage 9) сможет
звать refresh по таймеру или после событий.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal

from app.core.clock import utc_now
from app.core.events import AppStarted, CargoReceived, SourceHealthChanged, TelegramStatusChanged
from app.core.models.analytics import MatchingAnalytics
from app.core.models.matching import IntelligentCargoMatch
from app.ui.viewmodels.cards import (
    AnalyticsViewModel,
    BadgeTone,
    CargoCardViewModel,
    DashboardSnapshot,
    EventRowViewModel,
    SourceStatusViewModel,
    StatusBadge,
    VehicleViewModel,
    telegram_status_badge,
)
from app.ui.viewmodels.events import (
    CargoRecommendationChanged,
    DashboardUpdated,
    SourceStatusChanged,
)
from app.ui.viewmodels.ports import DashboardDataProvider, EventStream

_RECENT_EVENTS_LIMIT = 10


class DashboardViewModel:
    """Презентационное состояние дашборда (MVVM, слой без виджетов)."""

    def __init__(
        self,
        *,
        provider: DashboardDataProvider,
        events: EventStream,
        clock: Callable[[], datetime] = utc_now,
        recent_events_limit: int = _RECENT_EVENTS_LIMIT,
    ) -> None:
        self._provider = provider
        self._events = events
        self._clock = clock
        self._recent_events_limit = recent_events_limit

        self._started = False
        self._telegram = StatusBadge(tone=BadgeTone.MUTED, label="Не подключён")
        self._sources: dict[str, SourceStatusViewModel] = {}
        self._vehicle: VehicleViewModel | None = None
        self._cards: tuple[CargoCardViewModel, ...] = ()
        self._statistics = MatchingAnalytics()
        self._found_count = 0
        self._potential_profit: Decimal | None = None
        self._analytics = AnalyticsViewModel.empty()
        self._recent_events: tuple[EventRowViewModel, ...] = ()
        self._favorite_cards: tuple[CargoCardViewModel, ...] = ()
        self._notification_events: tuple[EventRowViewModel, ...] = ()

    # ── Свойства (контракт для View) ──────────────────────────────────────────

    @property
    def application_status(self) -> StatusBadge:
        """Общий статус приложения (светофор для статус-бара)."""
        if not self._started:
            return StatusBadge(tone=BadgeTone.MUTED, label="Запускается")
        problems: list[str] = []
        if self._telegram.tone is BadgeTone.ERROR:
            problems.append("Telegram: ошибка")
        failed = [vm.name for vm in self._sources.values() if vm.status.tone is BadgeTone.ERROR]
        problems.extend(f"{name}: недоступен" for name in failed)
        if problems:
            return StatusBadge(
                tone=BadgeTone.WARNING, label="Работает с проблемами", detail="; ".join(problems)
            )
        return StatusBadge(tone=BadgeTone.OK, label="Работает")

    @property
    def telegram_status(self) -> StatusBadge:
        """Состояние Telegram-подключения."""
        return self._telegram

    @property
    def sources_status(self) -> tuple[SourceStatusViewModel, ...]:
        """Карточки источников (в порядке провайдера)."""
        return tuple(self._sources.values())

    @property
    def active_vehicle(self) -> VehicleViewModel | None:
        """Активный транспорт; ``None`` — не настроен."""
        return self._vehicle

    @property
    def best_matches(self) -> tuple[CargoCardViewModel, ...]:
        """Рекомендованные грузы (лучший — первым)."""
        return self._cards

    @property
    def analytics_summary(self) -> AnalyticsViewModel:
        """Сводка аналитики."""
        return self._analytics

    @property
    def recent_events(self) -> tuple[EventRowViewModel, ...]:
        """Последние события журнала."""
        return self._recent_events

    def snapshot(self) -> DashboardSnapshot:
        """Полное состояние одним значением."""
        return DashboardSnapshot(
            application_status=self.application_status,
            telegram_status=self.telegram_status,
            sources_status=self.sources_status,
            active_vehicle=self.active_vehicle,
            best_matches=self.best_matches,
            analytics_summary=self.analytics_summary,
            recent_events=self.recent_events,
            favorite_matches=self._favorite_cards,
            notification_events=self._notification_events,
        )

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    def attach(self) -> None:
        """Подписаться на доменные события (зовёт composition root)."""
        self._events.subscribe(AppStarted, self._on_app_started)
        self._events.subscribe(TelegramStatusChanged, self._on_telegram_status)
        self._events.subscribe(SourceHealthChanged, self._on_source_health)
        self._events.subscribe(CargoReceived, self._on_cargo_received)

    def detach(self) -> None:
        """Отписаться (закрытие окна/приложения)."""
        self._events.unsubscribe(AppStarted, self._on_app_started)
        self._events.unsubscribe(TelegramStatusChanged, self._on_telegram_status)
        self._events.unsubscribe(SourceHealthChanged, self._on_source_health)
        self._events.unsubscribe(CargoReceived, self._on_cargo_received)

    async def refresh(self) -> DashboardSnapshot:
        """Полностью перечитать состояние из провайдера и оповестить UI."""
        provider = self._provider
        self._started = True
        self._telegram = telegram_status_badge(provider.telegram_state())
        vehicle = provider.active_vehicle()
        self._vehicle = VehicleViewModel.from_profile(vehicle) if vehicle is not None else None
        self._reload_sources()
        self._statistics = await provider.matching_statistics()
        self._found_count = sum(provider.cargo_counts().values())
        self._rebuild_analytics()
        now = self._clock()
        entries = await provider.recent_events(self._recent_events_limit)
        self._recent_events = tuple(EventRowViewModel.from_entry(e, now=now) for e in entries)
        favorites = await provider.favorite_cargos(200)
        self._favorite_cards = tuple(
            CargoCardViewModel.from_cargo(cargo, workflow_state="Избранное") for cargo in favorites
        )
        notifications = await provider.notification_history(100)
        self._notification_events = tuple(
            EventRowViewModel.from_notification(entry, now=now) for entry in notifications
        )
        snapshot = self.snapshot()
        self._events.publish(DashboardUpdated(snapshot=snapshot))
        return snapshot

    # ── Рекомендации ──────────────────────────────────────────────────────────

    def update_recommendations(self, ranked: Sequence[IntelligentCargoMatch]) -> None:
        """Принять результаты интеллектуального подбора (лучший — первым)."""
        cards = tuple(CargoCardViewModel.from_match(match) for match in ranked)
        potential = sum(
            (
                m.profit.net_profit
                for m in ranked
                if m.profit is not None and m.profit.net_profit > 0
            ),
            start=Decimal(0),
        )
        self.set_recommendation_cards(cards, potential_profit=potential)

    def set_recommendation_cards(
        self,
        cards: Sequence[CargoCardViewModel],
        *,
        potential_profit: Decimal | None = None,
    ) -> None:
        """Показать готовые карточки (мок-режим и будущие сценарии UI)."""
        self._cards = tuple(cards)
        self._potential_profit = potential_profit
        self._rebuild_analytics()
        self._events.publish(CargoRecommendationChanged(cards=self._cards))
        self._publish_dashboard()

    # ── Обработчики доменных событий ──────────────────────────────────────────

    def _on_app_started(self, event: AppStarted) -> None:
        self._started = True
        self._publish_dashboard()

    def _on_telegram_status(self, event: TelegramStatusChanged) -> None:
        self._telegram = telegram_status_badge(event.state, event.detail)
        self._publish_dashboard()

    def _on_source_health(self, event: SourceHealthChanged) -> None:
        self._refresh_source(event.source_id)

    def _on_cargo_received(self, event: CargoReceived) -> None:
        self._found_count = sum(self._provider.cargo_counts().values())
        self._rebuild_analytics()
        self._refresh_source(event.source_id)

    # ── Внутреннее ────────────────────────────────────────────────────────────

    def _reload_sources(self) -> None:
        healths = self._provider.sources_health()
        names = self._provider.source_names()
        counts = self._provider.cargo_counts()
        now = self._clock()
        self._sources = {
            source_id: SourceStatusViewModel.from_health(
                source_id,
                names.get(source_id, source_id),
                health,
                cargo_count=counts.get(source_id, 0),
                now=now,
            )
            for source_id, health in healths.items()
        }

    def _refresh_source(self, source_id: str) -> None:
        health = self._provider.sources_health().get(source_id)
        if health is None:
            return
        card = SourceStatusViewModel.from_health(
            source_id,
            self._provider.source_names().get(source_id, source_id),
            health,
            cargo_count=self._provider.cargo_counts().get(source_id, 0),
            now=self._clock(),
        )
        self._sources[source_id] = card
        self._events.publish(SourceStatusChanged(source=card))
        self._publish_dashboard()

    def _rebuild_analytics(self) -> None:
        self._analytics = AnalyticsViewModel.build(
            found_count=self._found_count,
            statistics=self._statistics,
            potential_profit=self._potential_profit,
        )

    def _publish_dashboard(self) -> None:
        self._events.publish(DashboardUpdated(snapshot=self.snapshot()))
