"""Тесты библиотеки компонентов дизайн-системы (offscreen)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6", reason="PySide6 не установлен в этом окружении")
pytest.importorskip("pytestqt", reason="pytest-qt не установлен в этом окружении")

from PySide6.QtWidgets import QWidget

from app.ui.theme import tokens
from app.ui.viewmodels import (
    MOCK_NOW,
    BadgeTone,
    EventRowViewModel,
    StatusBadge,
    mock_best_matches,
)
from app.ui.widgets import (
    Badge,
    Button,
    ButtonKind,
    CargoCardWidget,
    EmptyState,
    ErrorState,
    HeroCard,
    MetricCard,
    Modal,
    ScoreRing,
    SkeletonBlock,
    Sparkline,
    StatusIndicator,
    Timeline,
    ToastHost,
)
from app.ui.widgets.layouts import FlowLayout


def test_buttons_follow_design_tokens(qtbot: Any) -> None:
    primary = Button("Открыть груз", ButtonKind.PRIMARY)
    ghost = Button("Игнорировать", ButtonKind.GHOST, compact=True)
    qtbot.addWidget(primary)
    qtbot.addWidget(ghost)
    assert primary.height() == tokens.BUTTON_HEIGHT
    assert ghost.height() == tokens.BUTTON_HEIGHT_COMPACT
    assert tokens.BLUE in primary.styleSheet()


def test_badge_maps_tone(qtbot: Any) -> None:
    badge = Badge(StatusBadge(tone=BadgeTone.ERROR, label="Недоступен", detail="HTTP 503"))
    qtbot.addWidget(badge)
    assert badge.text() == "Недоступен"
    assert tokens.RED in badge.styleSheet()
    assert badge.toolTip() == "HTTP 503"


def test_status_indicator_tones(qtbot: Any) -> None:
    indicator = StatusIndicator(BadgeTone.OK)
    qtbot.addWidget(indicator)
    indicator.set_tone(BadgeTone.MUTED)
    assert indicator.tone is BadgeTone.MUTED
    indicator.set_tone(BadgeTone.ERROR)
    assert indicator.tone is BadgeTone.ERROR


def test_score_ring_thresholds(qtbot: Any) -> None:
    ring = ScoreRing()
    qtbot.addWidget(ring)
    ring.set_score(96, animate=False)
    assert ring.score == 96
    assert not ring.grab().isNull()  # дуга и glow рисуются
    ring.set_score(150, animate=False)
    assert ring.score == 100  # кламп


def test_sparkline_renders_series(qtbot: Any) -> None:
    chart = Sparkline()
    qtbot.addWidget(chart)
    chart.set_values((1.0, 3.0, 2.0, 5.0), color=tokens.GREEN)
    assert not chart.grab().isNull()


def test_metric_card_value_and_series(qtbot: Any) -> None:
    card = MetricCard("Сегодня найдено")
    qtbot.addWidget(card)
    card.set_text_value("542", hint="за сессию")
    assert card._value.text() == "542"
    card.show_series((1, 2, 3, 4, 5))
    assert card._sparkline.isVisibleTo(card)


def test_timeline_rows(qtbot: Any) -> None:
    timeline = Timeline()
    qtbot.addWidget(timeline)
    rows = (
        EventRowViewModel(
            title="🚚 Лучший груз найден",
            time_label="4 мин назад",
            severity="success",
            kind="notification",
            source="matching",
        ),
        EventRowViewModel(
            title="Ozon недоступен",
            time_label="42 мин назад",
            severity="warning",
            kind="error",
            source="ozon",
        ),
    )
    timeline.set_events(rows)
    assert timeline.rows_count() == 2


def test_hero_card_shows_and_ignores(qtbot: Any) -> None:
    ignored: list[str] = []
    hero = HeroCard(on_ignore=ignored.append)
    qtbot.addWidget(hero)
    hero.show_card(mock_best_matches()[0], animate=False)
    assert hero.current_card is not None
    assert hero._from_label.text() == "Москва"
    assert hero._to_label.text() == "Санкт-Петербург"
    assert hero._price.text() == "120 000 ₽"
    assert hero._ring.score == 98

    hero._ignore_current()
    assert hero.current_card is None
    assert ignored == ["cargo-spb"]


def test_cargo_card_widget_builds(qtbot: Any) -> None:
    explained: list[str] = []
    card = CargoCardWidget(
        mock_best_matches()[0], on_explain=lambda c: explained.append(c.cargo_id)
    )
    qtbot.addWidget(card)
    card._explain()
    assert explained == ["cargo-spb"]


def test_modal_opens_and_escapes(qtbot: Any) -> None:
    host = QWidget()
    host.resize(800, 600)
    qtbot.addWidget(host)
    host.show()
    modal = Modal(host)
    modal.show_content("Почему выбран", QWidget(modal))
    assert modal.isVisible()
    modal.close_overlay()
    assert not modal.isVisible()


def test_toast_host_stacks_and_limits(qtbot: Any) -> None:
    host = QWidget()
    host.resize(800, 600)
    qtbot.addWidget(host)
    host.show()
    toasts = ToastHost(host)
    for index in range(5):
        toasts.show_toast(f"Тост {index}", tone=BadgeTone.OK)
    assert len(toasts._toasts) <= 3
    assert toasts.isVisible()


def test_flow_layout_wraps(qtbot: Any) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host)
    for _ in range(4):
        flow.addWidget(SkeletonBlock(120, 20, host))
    narrow = flow.heightForWidth(140)  # помещается один блок в ряд
    wide = flow.heightForWidth(600)  # все в один ряд
    assert narrow > wide


def test_empty_and_error_states(qtbot: Any) -> None:
    empty = EmptyState("📦", "Пока нет грузов", "AI покажет карточки позже.")
    qtbot.addWidget(empty)
    retried: list[bool] = []
    error = ErrorState(
        "Не удалось обновить", "Проверьте сеть.", on_retry=lambda: retried.append(True)
    )
    qtbot.addWidget(error)
    assert empty.findChildren(type(empty)) == []
    assert not error.grab().isNull()


def test_status_indicator_used_time_label() -> None:
    """MOCK_NOW согласован с дизайн-примерами (защита от дрейфа демо)."""
    assert MOCK_NOW.hour == 12
