"""DashboardPage — главный экран: Hero, метрики, рекомендации, источники,
таймлайн, машина. Все данные — из DashboardSnapshot (viewmodels)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.pages.base import Page
from app.ui.theme import cascade
from app.ui.theme import tokens as t
from app.ui.viewmodels import (
    CargoCardViewModel,
    DashboardSnapshot,
    SourceStatusViewModel,
)
from app.ui.widgets import (
    CargoCardWidget,
    GlassCard,
    HeroCard,
    MetricCard,
    SectionLabel,
    SkeletonBlock,
    SourceRow,
    Timeline,
)
from app.ui.widgets.layouts import clear_layout

#: Демо-ряды для тонких графиков (реальные почасовые ряды — этап 9.1).
DEMO_SERIES: dict[str, tuple[float, ...]] = {
    "found": (12, 18, 14, 30, 26, 41, 38, 52, 47, 64, 58, 71),
    "matched": (1, 3, 2, 5, 4, 7, 6, 9, 8, 12, 11, 14),
    "profit": (60, 95, 80, 140, 120, 210, 180, 260, 240, 330, 300, 410),
}


class DashboardPage(Page):
    """Главный экран AI-диспетчера."""

    def __init__(
        self,
        *,
        on_explain: Callable[[CargoCardViewModel], None],
        on_ignore: Callable[[str], None],
        demo: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("dashboard", "Dashboard", parent)
        self._on_explain = on_explain
        self._demo = demo

        self.hero = HeroCard(on_ignore=on_ignore)
        self.hero.show_empty()
        self.content_layout.addWidget(self.hero)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(t.SPACE_L)
        self.metric_found = MetricCard("Сегодня найдено")
        self.metric_matched = MetricCard("Подходящих")
        self.metric_profit = MetricCard("Потенциально")
        for metric in (self.metric_found, self.metric_matched, self.metric_profit):
            metrics_row.addWidget(metric, stretch=1)
        self.content_layout.addLayout(metrics_row)
        if demo:
            self.metric_found.show_series(DEMO_SERIES["found"], color=t.BLUE)
            self.metric_matched.show_series(DEMO_SERIES["matched"], color=t.GREEN)
            self.metric_profit.show_series(DEMO_SERIES["profit"], color=t.GREEN)

        columns = QGridLayout()
        columns.setHorizontalSpacing(t.SPACE_L)
        columns.setVerticalSpacing(t.SPACE_L)
        columns.setColumnStretch(0, 3)
        columns.setColumnStretch(1, 2)

        recommendations_column = QVBoxLayout()
        recommendations_column.setSpacing(t.SPACE_M)
        recommendations_column.addWidget(SectionLabel("Рекомендации AI"))
        self._cards_container = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(t.SPACE_M)
        self._show_cards_skeleton()
        recommendations_column.addWidget(self._cards_container)
        recommendations_column.addStretch(1)
        columns.addLayout(recommendations_column, 0, 0)

        side_column = QVBoxLayout()
        side_column.setSpacing(t.SPACE_L)
        self._sources_card = GlassCard(self)
        sources_body = self._sources_card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        sources_body.addWidget(SectionLabel("Источники"))
        self._sources_layout = QVBoxLayout()
        self._sources_layout.setSpacing(t.SPACE_XS)
        sources_body.addLayout(self._sources_layout)
        side_column.addWidget(self._sources_card)

        self._timeline_card = GlassCard(self)
        timeline_body = self._timeline_card.body(margin=t.SPACE_L, spacing=t.SPACE_S)
        timeline_body.addWidget(SectionLabel("Активность"))
        self.timeline = Timeline(self._timeline_card)
        timeline_body.addWidget(self.timeline)
        side_column.addWidget(self._timeline_card)

        vehicle_card = GlassCard(self)
        self._vehicle_card = vehicle_card
        vehicle_body = vehicle_card.body(margin=t.SPACE_L, spacing=t.SPACE_XS)
        vehicle_body.addWidget(SectionLabel("Машина"))
        self._vehicle_name = QLabel("Не настроена", vehicle_card)
        self._vehicle_name.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 600; background: transparent; }}"
        )
        vehicle_body.addWidget(self._vehicle_name)
        self._vehicle_summary = QLabel("Добавьте профиль транспорта в настройках", vehicle_card)
        self._vehicle_summary.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
            f" background: transparent; }}"
        )
        self._vehicle_summary.setWordWrap(True)
        vehicle_body.addWidget(self._vehicle_summary)
        side_column.addWidget(vehicle_card)
        side_column.addStretch(1)
        columns.addLayout(side_column, 0, 1)

        self.content_layout.addLayout(columns)
        self._source_rows: dict[str, SourceRow] = {}
        self._shown_cards: tuple[CargoCardViewModel, ...] | None = None
        self._entrance_played = False

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt API)
        """Первый показ — каскад секций: Hero → метрики → рекомендации →
        источники → активность → машина (сдвиг 30–60 мс)."""
        super().showEvent(event)
        if self._entrance_played:
            return
        self._entrance_played = True
        cascade(
            (
                self.hero,
                self.metric_found,
                self.metric_matched,
                self.metric_profit,
                self._cards_container,
                self._sources_card,
                self._timeline_card,
                self._vehicle_card,
            ),
            step_ms=45,
        )

    # ── Обновления ────────────────────────────────────────────────────────────

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Полное обновление страницы из снапшота."""
        analytics = snapshot.analytics_summary
        self.metric_found.animate_value(
            analytics.today_found, formatter=lambda v: f"{v:,d}".replace(",", " ")
        )
        self.metric_matched.animate_value(
            analytics.matched_count, formatter=lambda v: f"{v:,d}".replace(",", " ")
        )
        self.metric_profit.set_text_value(
            analytics.potential_profit,
            hint=f"средняя {analytics.average_profit}" if analytics.average_profit != "—" else "",
        )

        self._apply_sources(snapshot.sources_status)
        self.timeline.set_events(snapshot.recent_events)

        vehicle = snapshot.active_vehicle
        if vehicle is not None:
            self._vehicle_name.setText(vehicle.name)
            self._vehicle_summary.setText(f"{vehicle.summary}\n{vehicle.dimensions}")
        self.show_recommendations(snapshot.best_matches, animate=False)

    def show_recommendations(
        self, cards: Sequence[CargoCardViewModel], *, animate: bool = True
    ) -> None:
        """Показать рекомендации; лучший груз уезжает в Hero.

        Неизменившийся список не перестраивается: событие рекомендаций и
        следом полный снапшот не должны дублировать работу и рвать анимации.
        """
        cards_tuple = tuple(cards)
        if cards_tuple == self._shown_cards:
            return
        self._shown_cards = cards_tuple
        self._clear_cards()
        if not cards_tuple:
            self._show_cards_skeleton()
            self.hero.show_empty()
            return
        self.hero.show_card(cards_tuple[0], animate=animate)
        for card in cards_tuple:
            widget = CargoCardWidget(card, on_explain=self._on_explain)
            self._cards_layout.addWidget(widget)

    def update_source(self, source: SourceStatusViewModel) -> None:
        """Точечное обновление строки источника."""
        row = self._source_rows.get(source.id)
        if row is not None:
            row.update_source(source)

    def cargo_widgets_count(self) -> int:
        """Число карточек рекомендаций (для тестов)."""
        count = 0
        for index in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(index)
            if item is not None and isinstance(item.widget(), CargoCardWidget):
                count += 1
        return count

    # ── Внутреннее ────────────────────────────────────────────────────────────

    def _apply_sources(self, sources: Sequence[SourceStatusViewModel]) -> None:
        clear_layout(self._sources_layout)
        self._source_rows = {}
        for source in sources:
            row = SourceRow(source, self._sources_card)
            self._source_rows[source.id] = row
            self._sources_layout.addWidget(row)

    def _clear_cards(self) -> None:
        clear_layout(self._cards_layout)

    def _show_cards_skeleton(self) -> None:
        for _ in range(2):
            self._cards_layout.addWidget(SkeletonBlock(560, 96, self._cards_container))
