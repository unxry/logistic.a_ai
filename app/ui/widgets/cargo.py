"""Доменные виджеты: HeroCard, CargoCardWidget, SourceRow.

Все данные приходят готовыми строками из app/ui/viewmodels — виджеты
ничего не считают и не форматируют.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.theme import count_up, materialize
from app.ui.theme import tokens as t
from app.ui.viewmodels import BadgeTone, CargoCardViewModel, SourceStatusViewModel, StatusBadge
from app.ui.widgets.atoms import (
    Badge,
    Button,
    ButtonKind,
    SectionLabel,
    SkeletonBlock,
    StatusIndicator,
)
from app.ui.widgets.cards import GlassCard, HoverCard
from app.ui.widgets.charts import ScoreRing
from app.ui.widgets.layouts import FlowLayout


def _open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def _meta_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setStyleSheet(
        f"QLabel {{ color: {t.TEXT_SECONDARY}; font-size: {t.CAPTION_PT}pt;"
        f" background: transparent; }}"
    )
    return label


def _elide(label: QLabel, text: str, max_px: int) -> None:
    """Обрезать текст многоточием (полный — в тултипе): длинные строки
    не должны раздувать минимальную ширину контента и выталкивать соседей."""
    metrics = QFontMetrics(label.font())
    elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_px)
    label.setText(elided)
    if elided != text:
        label.setToolTip(text)


def _accent_chip(text: str, color: str, parent: QWidget | None = None) -> QLabel:
    """Современный бейдж-капсула (AI 98, 120 ₽/км): тонированный фон + цвет."""
    chip = QLabel(text, parent)
    chip.setStyleSheet(
        f"QLabel {{ background: {t.tint(color, 0.12)}; color: {color};"
        f" border-radius: {t.RADIUS_CHIP}px; padding: 2px 9px;"
        f" font-size: {t.CAPTION_PT}pt; font-weight: 600; }}"
    )
    return chip


#: Иконка причины по смыслу текста (презентационная эвристика, не домен).
_REASON_ICONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("прибыль", "доход", "ставка выше", "маржа"), "📈"),
    (("маршрут", "плечо", "направлени", " км", "домой", "обратн"), "🛣"),
    (("цена", "₽/км", "тариф", "дорого", "оплат"), "💰"),
    (("совмести", "кузов", "тент", "вмеща", "габарит", "вес", "машин", "транспорт"), "🚚"),
)


def reason_icon(text: str) -> str:
    """Подобрать иконку для причины AI-объяснения."""
    lowered = text.casefold()
    for keywords, icon in _REASON_ICONS:
        if any(keyword in lowered for keyword in keywords):
            return icon
    return "✔"


class ReasonChip(QLabel):
    """Чип причины в объяснении AI: капсула с иконкой по смыслу текста."""

    def __init__(self, text: str, parent: QWidget | None = None, *, max_px: int = 210) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QLabel {{ background: {t.tint(t.GREEN, 0.10)}; color: {t.TEXT};"
            f" border-radius: {t.RADIUS_CHIP}px; padding: 3px 9px;"
            f" font-size: {t.CAPTION_PT}pt; }}"
        )
        _elide(self, f"{reason_icon(text)} {text}", max_px)


class ReasonCard(QFrame):
    """Причина в AI Explanation Sheet: стеклянная мини-карточка с иконкой."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReasonCard")
        self.setStyleSheet(
            f"QFrame#ReasonCard {{ background: {t.CARD}; border: 1px solid {t.BORDER};"
            f" border-radius: {t.RADIUS_CONTROL}px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.SPACE_M, t.SPACE_S + 2, t.SPACE_M, t.SPACE_S + 2)
        layout.setSpacing(t.SPACE_M)
        icon = QLabel(reason_icon(text), self)
        icon.setStyleSheet("QLabel { font-size: 14pt; background: transparent; }")
        icon.setFixedWidth(26)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(icon)
        body = QLabel(text, self)
        body.setWordWrap(True)
        body.setStyleSheet(f"QLabel {{ color: {t.TEXT}; background: transparent; }}")
        layout.addWidget(body, stretch=1)


def build_explanation_panel(card: CargoCardViewModel, parent: QWidget | None = None) -> QWidget:
    """Содержимое AI Explanation Sheet: причины-карточки + итоговый футер.

    Футер: AI Score · Совместимость · Прибыль · Маршрут — всё из viewmodel.
    """
    panel = QWidget(parent)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(t.SPACE_M)

    intro = QLabel(f"{card.route} · {card.price}", panel)
    intro.setStyleSheet(f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}")
    layout.addWidget(intro)

    for reason in card.explanation:
        layout.addWidget(ReasonCard(reason, panel))

    layout.addSpacing(t.SPACE_XS)
    summary = QFrame(panel)
    summary.setObjectName("ExplanationSummary")
    summary.setStyleSheet(
        f"QFrame#ExplanationSummary {{ background: {t.tint(t.BLUE, 0.07)};"
        f" border: 1px solid {t.tint(t.BLUE, 0.14)};"
        f" border-radius: {t.RADIUS_CONTROL}px; }}"
    )
    row = QHBoxLayout(summary)
    row.setContentsMargins(t.SPACE_L, t.SPACE_M, t.SPACE_L, t.SPACE_M)
    row.setSpacing(t.SPACE_L)
    for caption, value in (
        ("AI Score", str(card.score)),
        ("Совместимость", f"{card.compatibility}%"),
        ("Прибыль", card.profit),
        ("Маршрут", card.distance),
    ):
        column = QVBoxLayout()
        column.setSpacing(1)
        caption_label = QLabel(caption, summary)
        caption_label.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT - 1}pt;"
            f" font-weight: 600; background: transparent; }}"
        )
        value_label = QLabel(value, summary)
        value_label.setStyleSheet(
            f"QLabel {{ color: {t.TEXT}; font-size: {t.BODY_PT + 1}pt;"
            f" font-weight: 700; background: transparent; }}"
        )
        column.addWidget(caption_label)
        column.addWidget(value_label)
        row.addLayout(column)
    row.addStretch(1)
    layout.addWidget(summary)
    return panel


class HeroCard(GlassCard):
    """«Лучший груз сегодня»: маршрут, деньги, AI Score, действия.

    Появление нового лучшего груза — паттерн materialize (fade + рост),
    деньги и балл набегают count-up.
    """

    def __init__(
        self,
        *,
        on_open: Callable[[str], None] = _open_url,
        on_ignore: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, radius=t.RADIUS_HERO)
        self._on_open = on_open
        self._on_ignore = on_ignore
        self._card: CargoCardViewModel | None = None

        outer = self.body(margin=t.SPACE_XXL, spacing=t.SPACE_L)
        outer.addWidget(SectionLabel("Лучший груз сегодня"))

        self._stack = QWidget(self)
        outer.addWidget(self._stack)
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        self._empty = self._build_empty()
        stack_layout.addWidget(self._empty)
        self._content = self._build_content()
        self._content.setVisible(False)
        stack_layout.addWidget(self._content)

    # ── Публичный контракт ────────────────────────────────────────────────────

    def show_card(self, card: CargoCardViewModel, *, animate: bool = True) -> None:
        """Показать нового лучшего груза."""
        self._card = card
        self._empty.setVisible(False)
        self._content.setVisible(True)

        loading, _, unloading = card.route.partition(" → ")
        self._from_label.setText(loading or card.route)
        self._to_label.setText(unloading or "—")
        self._meta.setText(" · ".join(p for p in (card.distance, card.weight) if p != "—"))
        self._price.setText(card.price)
        self._profit_caption.setText("Чистая прибыль")
        self._open_button.setEnabled(bool(card.actions))
        if animate:
            materialize(self._content)
            self._animate_profit(card)
            self._ring.set_score(card.score, animate=True)
        else:
            self._profit.setText(card.profit)
            self._ring.set_score(card.score, animate=False)

    def show_empty(self) -> None:
        """AI ещё ищет: скелетон вместо цифр."""
        self._card = None
        self._content.setVisible(False)
        self._empty.setVisible(True)

    @property
    def current_card(self) -> CargoCardViewModel | None:
        """Текущий груз (для тестов и окна)."""
        return self._card

    # ── Внутреннее ────────────────────────────────────────────────────────────

    def _animate_profit(self, card: CargoCardViewModel) -> None:
        digits = "".join(ch for ch in card.profit if ch.isdigit())
        if digits:
            target = int(digits)
            suffix = " ₽" if "₽" in card.profit else ""
            sign = "-" if card.profit.strip().startswith("-") else ""

            def _format(value: int) -> str:
                return sign + f"{value:,d}".replace(",", " ") + suffix

            count_up(self._profit, target, formatter=_format)
        else:
            self._profit.setText(card.profit)

    def _build_empty(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, t.SPACE_S, 0, t.SPACE_S)
        layout.setSpacing(t.SPACE_M)
        row = QHBoxLayout()
        row.setSpacing(t.SPACE_S)
        indicator = StatusIndicator(BadgeTone.OK, panel)
        row.addWidget(indicator)
        text = QLabel("AI ищет лучший груз — появится здесь", panel)
        text.setStyleSheet(f"QLabel {{ color: {t.TEXT_SECONDARY}; background: transparent; }}")
        row.addWidget(text)
        row.addStretch(1)
        layout.addLayout(row)
        for width in (260, 200, 320):
            layout.addWidget(SkeletonBlock(width, 14, panel))
        return panel

    def _build_content(self) -> QWidget:
        panel = QWidget(self)
        columns = QHBoxLayout(panel)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(t.SPACE_XXL)

        route_column = QVBoxLayout()
        route_column.setSpacing(2)
        self._from_label = QLabel("", panel)
        self._from_label.setStyleSheet(
            f"QLabel {{ font-size: {t.TITLE_PT}pt; font-weight: 700; background: transparent; }}"
        )
        arrow = QLabel("↓", panel)
        arrow.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.HEADLINE_PT}pt;"
            f" background: transparent; }}"
        )
        self._to_label = QLabel("", panel)
        self._to_label.setStyleSheet(
            f"QLabel {{ font-size: {t.TITLE_PT}pt; font-weight: 700; background: transparent; }}"
        )
        self._meta = _meta_label("", panel)
        route_column.addWidget(self._from_label)
        route_column.addWidget(arrow)
        route_column.addWidget(self._to_label)
        route_column.addSpacing(t.SPACE_S)
        route_column.addWidget(self._meta)
        route_column.addStretch(1)
        columns.addLayout(route_column, stretch=2)

        money_column = QVBoxLayout()
        money_column.setSpacing(2)
        self._price = QLabel("", panel)
        self._price.setStyleSheet(
            f"QLabel {{ font-size: {t.DISPLAY_PT}pt; font-weight: 700; background: transparent; }}"
        )
        self._profit_caption = _meta_label("", panel)
        self._profit = QLabel("", panel)
        self._profit.setStyleSheet(
            f"QLabel {{ font-size: {t.TITLE_PT}pt; font-weight: 700; color: {t.GREEN};"
            f" background: transparent; }}"
        )
        money_column.addWidget(self._price)
        money_column.addSpacing(t.SPACE_S)
        money_column.addWidget(self._profit_caption)
        money_column.addWidget(self._profit)
        money_column.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(t.SPACE_S)
        self._open_button = Button("Открыть груз", ButtonKind.PRIMARY)
        self._open_button.clicked.connect(self._open_current)
        ignore_button = Button("Игнорировать", ButtonKind.GHOST)
        ignore_button.clicked.connect(self._ignore_current)
        buttons.addWidget(self._open_button)
        buttons.addWidget(ignore_button)
        buttons.addStretch(1)
        money_column.addLayout(buttons)
        columns.addLayout(money_column, stretch=3)

        ring_column = QVBoxLayout()
        ring_column.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self._ring = ScoreRing(panel)
        ring_column.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignRight)
        ring_caption = _meta_label("AI Score", panel)
        ring_caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ring_column.addWidget(ring_caption, alignment=Qt.AlignmentFlag.AlignHCenter)
        columns.addLayout(ring_column, stretch=1)
        return panel

    def _open_current(self) -> None:
        if self._card is not None and self._card.actions:
            self._on_open(self._card.actions[0].url)

    def _ignore_current(self) -> None:
        card = self._card
        self.show_empty()
        if card is not None and self._on_ignore is not None:
            self._on_ignore(card.cargo_id)


class CargoCardWidget(HoverCard):
    """Карточка груза: маршрут, метрики, деньги, совместимость, «почему»."""

    def __init__(
        self,
        card: CargoCardViewModel,
        *,
        on_explain: Callable[[CargoCardViewModel], None] | None = None,
        on_favorite: Callable[[str], None] | None = None,
        on_ignore: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.card = card
        self._on_explain = on_explain
        self._on_favorite = on_favorite
        self._on_ignore = on_ignore
        layout = self.body(margin=t.SPACE_XL, spacing=t.SPACE_M)

        top_host = QWidget(self)
        top = FlowLayout(top_host, h_spacing=t.SPACE_S, v_spacing=t.SPACE_XS)
        route = QLabel(card.route, top_host)
        route.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 600;"
            f" letter-spacing: -0.1px; background: transparent; }}"
        )
        top.addWidget(route)
        if card.score > 0:
            top.addWidget(_accent_chip(f"AI {card.score}", t.BLUE, top_host))
        if card.compatibility > 0:
            top.addWidget(
                Badge(
                    StatusBadge(
                        tone=BadgeTone.OK if card.compatibility >= 90 else BadgeTone.WARNING,
                        label=f"{card.compatibility}%",
                    ),
                    top_host,
                )
            )
        if card.workflow_state:
            top.addWidget(_accent_chip(card.workflow_state, t.GREEN, top_host))
        layout.addWidget(top_host)

        meta_parts = [p for p in (card.distance, card.weight, card.dimensions) if p != "—"]
        layout.addWidget(_meta_label(" · ".join(meta_parts) if meta_parts else "—", self))

        money_host = QWidget(self)
        money = FlowLayout(money_host, h_spacing=t.SPACE_M, v_spacing=t.SPACE_XS)
        price = QLabel(card.price, money_host)
        price.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 700; background: transparent; }}"
        )
        money.addWidget(price)
        profit_text = (
            card.profit
            if card.profit in ("—",) or card.profit.startswith("-")
            else (f"+{card.profit}")
        )
        profit_color = t.RED if card.profit.startswith("-") else t.GREEN
        profit = QLabel(profit_text, money_host)
        profit.setStyleSheet(
            f"QLabel {{ font-size: {t.HEADLINE_PT}pt; font-weight: 700;"
            f" color: {profit_color}; background: transparent; }}"
        )
        money.addWidget(profit)
        if card.profit_per_km:
            money.addWidget(_accent_chip(card.profit_per_km, t.GREEN, money_host))
        layout.addWidget(money_host)

        if card.explanation:
            reasons_host = QWidget(self)
            reasons = FlowLayout(reasons_host, h_spacing=t.SPACE_XS, v_spacing=t.SPACE_XS)
            for reason in card.explanation[:3]:
                reasons.addWidget(ReasonChip(reason, reasons_host))
            layout.addWidget(reasons_host)

        actions = QWidget(self)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(t.SPACE_S)
        if card.actions:
            open_button = Button(card.actions[0].label, ButtonKind.PRIMARY, compact=True)
            open_button.clicked.connect(lambda: _open_url(card.actions[0].url))
            actions_layout.addWidget(open_button)
        explain_button = Button("Почему выбран", ButtonKind.GHOST, compact=True)
        explain_button.clicked.connect(self._explain)
        actions_layout.addWidget(explain_button)
        favorite_button = Button("В избранное", ButtonKind.GHOST, compact=True)
        favorite_button.clicked.connect(self._favorite)
        actions_layout.addWidget(favorite_button)
        ignore_button = Button("Игнорировать", ButtonKind.GHOST, compact=True)
        ignore_button.clicked.connect(self._ignore)
        actions_layout.addWidget(ignore_button)
        actions_layout.addStretch(1)
        layout.addWidget(actions)
        self.reveal_on_hover(actions)

    def _explain(self) -> None:
        if self._on_explain is not None:
            self._on_explain(self.card)

    def _favorite(self) -> None:
        if self._on_favorite is not None:
            self._on_favorite(self.card.cargo_id)

    def _ignore(self) -> None:
        if self._on_ignore is not None:
            self._on_ignore(self.card.cargo_id)


class SourceRow(QWidget):
    """Строка источника: живой индикатор, имя, синхронизация, счётчик."""

    def __init__(self, source: SourceStatusViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source_id = source.id
        self.setObjectName("SourceRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hover_bg = (
            "rgba(255, 255, 255, 0.05)" if t.CURRENT_THEME == "dark" else "rgba(9, 17, 33, 0.04)"
        )
        self.setStyleSheet(
            f"QWidget#SourceRow {{ background: transparent; border-radius: {t.RADIUS_CHIP}px; }}"
            f"QWidget#SourceRow:hover {{ background: {hover_bg}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.SPACE_XS, t.SPACE_XS, t.SPACE_XS, t.SPACE_XS)
        layout.setSpacing(t.SPACE_S)

        self._indicator = StatusIndicator(source.status.tone, self)
        layout.addWidget(self._indicator)

        text_column = QVBoxLayout()
        text_column.setSpacing(1)
        name = QLabel(source.name, self)
        name.setStyleSheet("QLabel { font-weight: 600; background: transparent; }")
        text_column.addWidget(name)
        self._caption = _meta_label("", self)
        _elide(self._caption, source.errors if source.errors else source.last_sync, 190)
        text_column.addWidget(self._caption)
        layout.addLayout(text_column, stretch=1)

        self._badge = Badge(source.status, self)
        layout.addWidget(self._badge)
        self._count = QLabel(f"{source.cargo_count}", self)
        self._count.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_SECONDARY}; font-weight: 600; background: transparent; }}"
        )
        self._count.setToolTip("Грузов получено")
        layout.addWidget(self._count)

    def update_source(self, source: SourceStatusViewModel) -> None:
        """Обновить строку по новому состоянию."""
        self._indicator.set_tone(source.status.tone)
        self._badge.set_badge(source.status)
        _elide(self._caption, source.errors if source.errors else source.last_sync, 190)
        self._count.setText(f"{source.cargo_count}")
