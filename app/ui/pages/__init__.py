"""Страницы приложения (тонкие представления DashboardSnapshot)."""

from app.ui.pages.base import Page
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.sections import (
    AnalyticsPage,
    CargoPage,
    FavoritesPage,
    NotificationHistoryPage,
    SearchPage,
    SettingsPage,
    SourcesPage,
    VehiclePage,
)

__all__ = [
    "AnalyticsPage",
    "CargoPage",
    "DashboardPage",
    "FavoritesPage",
    "NotificationHistoryPage",
    "Page",
    "SearchPage",
    "SettingsPage",
    "SourcesPage",
    "VehiclePage",
]
