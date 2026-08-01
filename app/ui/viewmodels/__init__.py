"""ViewModel'и (MVVM): готовые контракты данных для UI, без Qt (Stage 8.6).

Всё, что нужно UI-агенту: карточные ViewModel (cards), презентер дашборда
(DashboardViewModel), UI-события (DashboardUpdated и др.), порты данных
и мок-провайдер с красивыми детерминированными данными. Контракт «без Qt
и без конкретных слоёв» закреплён import-linter.
"""

from app.ui.viewmodels.cards import (
    ActionViewModel,
    AnalyticsViewModel,
    BadgeTone,
    CargoCardViewModel,
    DashboardSnapshot,
    EventRowViewModel,
    SourceStatusViewModel,
    StatusBadge,
    VehicleViewModel,
    source_status_badge,
    telegram_status_badge,
)
from app.ui.viewmodels.dashboard import DashboardViewModel
from app.ui.viewmodels.events import (
    CargoRecommendationChanged,
    DashboardUpdated,
    SourceStatusChanged,
)
from app.ui.viewmodels.main_viewmodel import MainViewModel
from app.ui.viewmodels.mock_data import (
    MOCK_NOW,
    MOCK_POTENTIAL_PROFIT,
    MockDashboardDataProvider,
    mock_best_matches,
    mock_vehicle,
)
from app.ui.viewmodels.ports import CommandDispatcher, DashboardDataProvider, EventStream
from app.ui.viewmodels.serialization import snapshot_dict

__all__ = [
    "MOCK_NOW",
    "MOCK_POTENTIAL_PROFIT",
    "ActionViewModel",
    "AnalyticsViewModel",
    "BadgeTone",
    "CargoCardViewModel",
    "CargoRecommendationChanged",
    "CommandDispatcher",
    "DashboardDataProvider",
    "DashboardSnapshot",
    "DashboardUpdated",
    "DashboardViewModel",
    "EventRowViewModel",
    "EventStream",
    "MainViewModel",
    "MockDashboardDataProvider",
    "SourceStatusChanged",
    "SourceStatusViewModel",
    "StatusBadge",
    "VehicleViewModel",
    "mock_best_matches",
    "mock_vehicle",
    "snapshot_dict",
    "source_status_badge",
    "telegram_status_badge",
]
