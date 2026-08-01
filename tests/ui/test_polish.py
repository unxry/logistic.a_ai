"""Stage 9.8: премиальный полиш — капсула сайдбара, sheet, палитра, каскад.

Проверяется поведение, а не пиксели: позиции, состояния анимаций,
структура построенных виджетов.
"""

from __future__ import annotations

from typing import Any

import shiboken6
from PySide6.QtCore import QPointF, QVariantAnimation
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.theme import AnimationManager, animate_shadow, cascade, enter_page, tokens
from app.ui.viewmodels import BadgeTone, mock_best_matches
from app.ui.widgets import (
    CargoCardWidget,
    Command,
    CommandPalette,
    EmptyState,
    HoverCard,
    IllustrationBadge,
    Modal,
    ScoreRing,
    Sidebar,
    Sparkline,
    build_explanation_panel,
    reason_icon,
)
from app.ui.widgets.overlays import _highlight

_RUNNING = QVariantAnimation.State.Running


def _shown_sidebar(qtbot: Any) -> Sidebar:
    bar = Sidebar("LogistAI 0.1.0")
    qtbot.addWidget(bar)
    bar.show()
    layout = bar._nav_host.layout()
    assert layout is not None
    layout.activate()
    qtbot.wait(20)
    return bar


def test_sidebar_capsule_follows_selection(qtbot: Any) -> None:
    bar = _shown_sidebar(qtbot)
    bar.select("analytics")
    assert bar._buttons["analytics"].isChecked()
    bar._snap_capsule()
    assert bar._capsule.isVisible()
    assert bar._capsule.geometry() == bar._buttons["analytics"].geometry()


def test_sidebar_capsule_slides_with_animation(qtbot: Any) -> None:
    bar = _shown_sidebar(qtbot)
    bar._snap_capsule()
    bar.select("settings")
    animation = bar._capsule_animation
    assert animation is not None and animation.state() == _RUNNING
    qtbot.wait(tokens.DURATION_BASE + 150)
    assert bar._capsule.geometry() == bar._buttons["settings"].geometry()


def test_sidebar_status_pill_and_footer_badges(qtbot: Any) -> None:
    bar = _shown_sidebar(qtbot)
    bar.set_ai_tone(BadgeTone.OK)
    assert "AI активен" in bar._pill_label.text()
    bar.set_link_tones(BadgeTone.OK, BadgeTone.ERROR, BadgeTone.MUTED)
    assert tokens.GREEN in bar._badge_telegram.styleSheet()
    assert tokens.RED in bar._badge_ati.styleSheet()
    assert tokens.MUTED in bar._badge_scheduler.styleSheet()


def test_command_palette_rows_have_icons_and_hotkeys(qtbot: Any) -> None:
    host = QWidget()
    host.resize(900, 700)
    qtbot.addWidget(host)
    host.show()
    palette = CommandPalette(host)
    palette.set_commands(
        (
            Command(
                id="analytics",
                title="Открыть аналитику",
                run=lambda: None,
                shortcut="⌘5",
                icon="📊",
            ),
        )
    )
    palette.open_palette()
    item = palette._list.item(0)
    row = palette._list.itemWidget(item)
    assert row is not None
    labels = [label.text() for label in row.findChildren(QLabel)]
    assert "📊" in labels
    assert "⌘5" in labels


def test_palette_highlight_marks_match_and_escapes_html() -> None:
    marked = _highlight("Открыть аналитику", "анал")
    assert "<span" in marked and "анал" in marked
    assert _highlight("<b>x</b>", "") == "&lt;b&gt;x&lt;/b&gt;"
    assert "<script>" not in _highlight("<script>alert</script>", "alert")


def test_modal_sheet_sits_near_top(qtbot: Any) -> None:
    host = QWidget()
    host.resize(800, 600)
    qtbot.addWidget(host)
    host.show()
    modal = Modal(host)
    modal.show_content("Почему выбран", QWidget(modal))
    qtbot.wait(tokens.DURATION_ENTER + 100)
    assert modal.isVisible()
    assert modal._panel.y() <= modal.height() // 3  # sheet у верхней кромки


def test_explanation_panel_builds_reasons_and_summary(qtbot: Any) -> None:
    card = mock_best_matches()[0]
    panel = build_explanation_panel(card)
    qtbot.addWidget(panel)
    texts = [label.text() for label in panel.findChildren(QLabel)]
    assert "AI Score" in texts
    assert str(card.score) in texts
    assert "Совместимость" in texts
    assert any(reason in text for reason in card.explanation for text in texts)


def test_reason_icons_follow_meaning() -> None:
    assert reason_icon("Прибыль выше средней") == "📈"
    assert reason_icon("Маршрут совпадает с домашним плечом") == "🛣"
    assert reason_icon("Груз полностью совместим с кузовом") == "🚚"
    assert reason_icon("Хорошая цена за ₽/км") == "💰"
    assert reason_icon("Просто причина") == "✔"


def test_score_ring_pulse_only_while_visible(qtbot: Any) -> None:
    ring = ScoreRing()
    qtbot.addWidget(ring)
    ring.show()
    ring.set_score(90, animate=False)
    assert ring._pulse.state() == _RUNNING
    ring.hide()
    assert ring._pulse.state() != _RUNNING
    ring.show()
    assert ring._pulse.state() == _RUNNING


def test_sparkline_idempotent_series_and_endpoint(qtbot: Any) -> None:
    chart = Sparkline()
    qtbot.addWidget(chart)
    chart.set_values((1.0, 2.0, 3.0))
    assert chart._reveal == 1.0  # за кадром — без анимации отрисовки
    chart.set_values((1.0, 2.0, 3.0))  # идентичный ряд не перезапускает
    assert chart._reveal == 1.0
    chart.show()
    assert chart._pulse.state() == _RUNNING
    chart.hide()
    assert chart._pulse.state() != _RUNNING
    assert not chart.grab().isNull()


def test_shadow_deleted_safe(qtbot: Any) -> None:
    card = HoverCard()
    qtbot.addWidget(card)
    card.show()
    shadow = card._shadow
    old_effect = shadow.effect
    card.setGraphicsEffect(None)  # Qt owns and may delete the C++ effect.
    if old_effect is not None:
        assert not shiboken6.isValid(old_effect)

    animate_shadow(shadow, tokens.SHADOW_LIFTED, duration_ms=60)
    qtbot.wait(120)

    assert card.graphicsEffect() is not None


def test_hover_cancel_previous_animation(qtbot: Any) -> None:
    card = HoverCard()
    qtbot.addWidget(card)
    card.show()

    first = animate_shadow(card._shadow, tokens.SHADOW_LIFTED, duration_ms=300)
    second = animate_shadow(card._shadow, tokens.SHADOW_RESTING, duration_ms=300)

    assert first is not None and second is not None and first is not second
    assert first.state() != _RUNNING
    assert second.state() == _RUNNING


def test_hidden_widget_stops_animation(qtbot: Any) -> None:
    card = HoverCard()
    qtbot.addWidget(card)
    card.show()
    animate_shadow(card._shadow, tokens.SHADOW_LIFTED, duration_ms=300)
    assert AnimationManager.instance()._animations.get(card)

    card.hide()

    assert not AnimationManager.instance()._animations.get(card)


def test_cargo_card_hover_no_geometry_change(qtbot: Any) -> None:
    widget = CargoCardWidget(mock_best_matches()[0], on_explain=lambda _: None)
    qtbot.addWidget(widget)
    widget.resize(640, widget.sizeHint().height())
    widget.show()
    before = widget.geometry()

    event = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
    widget.enterEvent(event)
    qtbot.wait(80)

    assert widget.geometry() == before


def test_empty_state_has_illustration(qtbot: Any) -> None:
    empty = EmptyState("📦", "Пока нет грузов", "AI покажет карточки позже.")
    qtbot.addWidget(empty)
    assert empty.findChildren(IllustrationBadge)


def test_cascade_installs_then_removes_effects(qtbot: Any) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    first = QLabel("a", host)
    second = QLabel("b", host)
    cascade((first, second), step_ms=10, duration_ms=60)
    assert first.graphicsEffect() is not None
    assert second.graphicsEffect() is not None
    qtbot.wait(500)
    assert first.graphicsEffect() is None
    assert second.graphicsEffect() is None


def test_enter_page_restores_margins(qtbot: Any) -> None:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 24, 24, 24)
    qtbot.addWidget(page)
    page.show()
    enter_page(page, duration_ms=60)
    qtbot.wait(400)
    margins = layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        24,
        24,
        24,
        24,
    )
    assert page.graphicsEffect() is None
