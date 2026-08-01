"""UiEventBridge — три UI-события презентационного слоя как Qt-сигналы.

Виджеты не подписываются на шину напрямую: мост переводит DashboardUpdated /
CargoRecommendationChanged / SourceStatusChanged в сигналы, и весь UI живёт
в идиоматике Qt (connect/disconnect, автоматическая очистка при удалении).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.ui.viewmodels import (
    CargoRecommendationChanged,
    DashboardUpdated,
    EventStream,
    SourceStatusChanged,
)


class UiEventBridge(QObject):
    """Подписчик UI Event Stream, ретранслирующий события сигналами."""

    dashboard_updated = Signal(object)  # DashboardSnapshot
    recommendations_changed = Signal(object)  # tuple[CargoCardViewModel, ...]
    source_changed = Signal(object)  # SourceStatusViewModel

    def __init__(self, events: EventStream, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._events = events
        events.subscribe(DashboardUpdated, self._on_dashboard)
        events.subscribe(CargoRecommendationChanged, self._on_recommendations)
        events.subscribe(SourceStatusChanged, self._on_source)

    def detach(self) -> None:
        """Отписаться от шины (закрытие приложения)."""
        self._events.unsubscribe(DashboardUpdated, self._on_dashboard)
        self._events.unsubscribe(CargoRecommendationChanged, self._on_recommendations)
        self._events.unsubscribe(SourceStatusChanged, self._on_source)

    def _on_dashboard(self, event: DashboardUpdated) -> None:
        self.dashboard_updated.emit(event.snapshot)

    def _on_recommendations(self, event: CargoRecommendationChanged) -> None:
        self.recommendations_changed.emit(event.cards)

    def _on_source(self, event: SourceStatusChanged) -> None:
        self.source_changed.emit(event.source)
