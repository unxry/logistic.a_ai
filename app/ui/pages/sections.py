"""Разделы приложения: Грузы, Машина, Поиск, Аналитика, Источники, Настройки.

Все страницы — тонкие представления DashboardSnapshot; функциональные экраны
(настройки с токеном, живой поиск) подключаются на этапе 9.1 поверх этих же
каркасов.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.pages.base import Page
from app.ui.pages.dashboard import DEMO_SERIES
from app.ui.theme import tokens as t
from app.ui.viewmodels import CargoCardViewModel, DashboardSnapshot
from app.ui.widgets import (
    Badge,
    CargoCardWidget,
    EmptyState,
    GlassCard,
    MetricCard,
    SectionLabel,
    SourceRow,
    Sparkline,
    Timeline,
)
from app.ui.widgets.layouts import clear_layout


class CargoPage(Page):
    """«Грузы» — все текущие рекомендации карточками (не таблицей)."""

    def __init__(
        self,
        *,
        on_explain: Callable[[CargoCardViewModel], None],
        on_favorite: Callable[[str], None] | None = None,
        on_ignore: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("cargo", "Грузы", parent)
        self._on_explain = on_explain
        self._on_favorite = on_favorite
        self._on_ignore = on_ignore
        self._empty = EmptyState(
            "📦",
            "Пока нет подходящих грузов",
            "AI покажет здесь карточки, как только источники начнут отдавать заказы.",
        )
        self.content_layout.addWidget(self._empty)
        self._cards = QVBoxLayout()
        self._cards.setSpacing(t.SPACE_M)
        self.content_layout.addLayout(self._cards)
        self.content_layout.addStretch(1)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Обновить список карточек."""
        clear_layout(self._cards)
        cards = snapshot.best_matches
        self._empty.setVisible(not cards)
        for card in cards:
            self._cards.addWidget(
                CargoCardWidget(
                    card,
                    on_explain=self._on_explain,
                    on_favorite=self._on_favorite,
                    on_ignore=self._on_ignore,
                )
            )


class FavoritesPage(Page):
    """«Избранное» — сохранённые грузы, не исчезающие после новых поисков."""

    def __init__(
        self,
        *,
        on_explain: Callable[[CargoCardViewModel], None],
        on_ignore: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("favorites", "Избранное", parent)
        self._on_explain = on_explain
        self._on_ignore = on_ignore
        self._empty = EmptyState(
            "⭐",
            "Избранных грузов пока нет",
            "Сохраняйте сильные предложения — они останутся здесь после новых поисков.",
        )
        self.content_layout.addWidget(self._empty)
        self._cards = QVBoxLayout()
        self._cards.setSpacing(t.SPACE_M)
        self.content_layout.addLayout(self._cards)
        self.content_layout.addStretch(1)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Обновить список избранного."""
        clear_layout(self._cards)
        cards = snapshot.favorite_matches
        self._empty.setVisible(not cards)
        for card in cards:
            self._cards.addWidget(
                CargoCardWidget(
                    card,
                    on_explain=self._on_explain,
                    on_ignore=self._on_ignore,
                )
            )


class NotificationHistoryPage(Page):
    """«История уведомлений» — полный Timeline уведомлений."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("notifications", "История уведомлений", parent)
        card = GlassCard(self)
        body = card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        body.addWidget(SectionLabel("Timeline"))
        self._timeline = Timeline(card)
        body.addWidget(self._timeline)
        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Показать историю уведомлений."""
        self._timeline.set_events(snapshot.notification_events)


class VehiclePage(Page):
    """«Машина» — активный профиль транспорта."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("vehicle", "Машина", parent)
        self._empty = EmptyState(
            "🚗",
            "Профиль транспорта не настроен",
            "Добавьте машину в настройках — подбор учитывает кузов, тоннаж и объём.",
        )
        self.content_layout.addWidget(self._empty)
        self._card = GlassCard(self)
        body = self._card.body()
        body.addWidget(SectionLabel("Активный профиль"))
        self._name = QLabel("", self._card)
        self._name.setStyleSheet(
            f"QLabel {{ font-size: {t.TITLE_PT}pt; font-weight: 700; background: transparent; }}"
        )
        body.addWidget(self._name)
        self._summary = QLabel("", self._card)
        self._summary.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}"
        )
        body.addWidget(self._summary)
        self._dimensions = QLabel("", self._card)
        self._dimensions.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}"
        )
        body.addWidget(self._dimensions)
        self._card.setVisible(False)
        self.content_layout.addWidget(self._card)
        self.content_layout.addStretch(1)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Показать активную машину или пустое состояние."""
        vehicle = snapshot.active_vehicle
        self._empty.setVisible(vehicle is None)
        self._card.setVisible(vehicle is not None)
        if vehicle is not None:
            self._name.setText(vehicle.name)
            self._summary.setText(vehicle.summary)
            self._dimensions.setText(f"Кузов внутри: {vehicle.dimensions}")


class SearchPage(Page):
    """«Поиск» — появится вместе с живыми источниками (этап 5.2)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("search", "Поиск", parent)
        self.content_layout.addWidget(
            EmptyState(
                "🔍",
                "Ручной поиск подключается вместе с живым ATI",
                "Сейчас AI ищет автоматически по расписанию источников. Ручные запросы "
                "с фильтрами появятся на этапе 5.2 — движок поиска уже готов.",
            )
        )
        self.content_layout.addStretch(1)


class AnalyticsPage(Page):
    """«Аналитика» — метрики, динамика и лучшие направления."""

    def __init__(self, *, demo: bool = False, parent: QWidget | None = None) -> None:
        super().__init__("analytics", "Аналитика", parent)
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(t.SPACE_L)
        self._found = MetricCard("Сегодня найдено")
        self._matched = MetricCard("Подходящих")
        self._potential = MetricCard("Потенциально")
        self._rejected = MetricCard("Отказов")
        self._score = MetricCard("Средний AI Score")
        for metric in (self._found, self._matched, self._potential, self._rejected, self._score):
            metrics_row.addWidget(metric, stretch=1)
        self.content_layout.addLayout(metrics_row)

        chart_card = GlassCard(self)
        chart_body = chart_card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        chart_body.addWidget(SectionLabel("Динамика находок"))
        self._chart = Sparkline(chart_card)
        self._chart.setFixedHeight(72)
        chart_body.addWidget(self._chart)
        self._chart_hint = QLabel("Почасовые ряды подключатся на этапе 9.1", chart_card)
        self._chart_hint.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT}pt;"
            f" background: transparent; }}"
        )
        chart_body.addWidget(self._chart_hint)
        if demo:
            self._chart.set_values(DEMO_SERIES["found"], color=t.BLUE)
            self._chart_hint.setText("Демо-ряд (реальные почасовые ряды — этап 9.1)")
        self.content_layout.addWidget(chart_card)

        routes_card = GlassCard(self)
        routes_body = routes_card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        routes_body.addWidget(SectionLabel("Лучшее направление"))
        self._best_route = QLabel("—", routes_card)
        self._best_route.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 600; background: transparent; }}"
        )
        routes_body.addWidget(self._best_route)
        self._average = QLabel("", routes_card)
        self._average.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}"
        )
        routes_body.addWidget(self._average)
        self.content_layout.addWidget(routes_card)
        self.content_layout.addStretch(1)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Обновить метрики и направления."""
        analytics = snapshot.analytics_summary
        self._found.animate_value(
            analytics.today_found, formatter=lambda v: f"{v:,d}".replace(",", " ")
        )
        self._matched.animate_value(
            analytics.matched_count, formatter=lambda v: f"{v:,d}".replace(",", " ")
        )
        self._potential.set_text_value(analytics.potential_profit)
        self._rejected.animate_value(analytics.rejected_count)
        self._score.set_text_value(analytics.average_score)
        self._best_route.setText(analytics.best_route)
        self._average.setText(
            f"Средняя прибыль выбранных грузов: {analytics.average_profit}"
            if analytics.average_profit != "—"
            else "Средняя прибыль появится после первых выборов AI"
        )


class SourcesPage(Page):
    """«Источники» — здоровье подключений с живыми индикаторами."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("sources", "Источники", parent)
        self._card = GlassCard(self)
        self._body = self._card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        self._body.addWidget(SectionLabel("Подключения"))
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(t.SPACE_XS)
        self._body.addLayout(self._rows_layout)
        self.content_layout.addWidget(self._card)
        hint = QLabel(
            "ATI поставляется выключенным и оживает после ввода ключа (этап 5.2). "
            "Ozon, WB и CSV-импорт подключаются конфигурацией — код не меняется.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}")
        self.content_layout.addWidget(hint)
        self.content_layout.addStretch(1)
        self._rows: dict[str, SourceRow] = {}

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Перестроить список источников."""
        clear_layout(self._rows_layout)
        self._rows = {}
        for source in snapshot.sources_status:
            row = SourceRow(source, self._card)
            self._rows[source.id] = row
            self._rows_layout.addWidget(row)


class SettingsPage(Page):
    """«Настройки» — каркас; формы (токен, Chat ID, тарифы) — этап 9.1."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("settings", "Настройки", parent)
        status_card = GlassCard(self)
        body = status_card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        body.addWidget(SectionLabel("Telegram"))
        row = QHBoxLayout()
        row.setSpacing(t.SPACE_S)
        self._telegram_badge = Badge(parent=status_card)
        row.addWidget(self._telegram_badge)
        row.addStretch(1)
        body.addLayout(row)
        self.content_layout.addWidget(status_card)
        self.content_layout.addWidget(
            EmptyState(
                "⚙️",
                "Формы настроек подключаются на этапе 9.1",
                "Токен бота и Chat ID хранятся в Keychain, тарифы маршрутов и веса "
                "подбора — в settings.json. Движок настроек и команды уже готовы.",
            )
        )
        self.content_layout.addStretch(1)

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Показать текущее состояние Telegram."""
        self._telegram_badge.set_badge(snapshot.telegram_status)
