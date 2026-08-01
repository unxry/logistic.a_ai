"""Motion-паттерны дизайн-системы: materialize, count-up, lift, fade,
cascade (каскад секций), enter_page (переход раздела), breathing (пульс).

Все анимации короткие (≤ ENTER), прерываемые и работают только с
прозрачностью/тенью/полями — тяжёлого relayout нет. Бесконечные циклы
(breathing) владелец обязан останавливать в hideEvent: анимации
невидимых виджетов не работают (правило производительности Stage 9.8).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import shiboken6
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QWidget,
)

from app.ui.theme import tokens as t

_ENTRANCE_ANIMATION_PROPERTY = "_logistai_entrance_animation"


def _restart_entrance(widget: QWidget, animation: QVariantAnimation) -> None:
    """Прервать предыдущую входную анимацию виджета (анимации прерываемы)."""
    previous = widget.property(_ENTRANCE_ANIMATION_PROPERTY)
    if isinstance(previous, QVariantAnimation) and shiboken6.isValid(previous):
        previous.stop()
    widget.setProperty(_ENTRANCE_ANIMATION_PROPERTY, animation)


def apply_shadow(widget: QWidget, spec: t.ShadowSpec) -> QGraphicsDropShadowEffect:
    """Повесить теневой эффект уровня дизайн-системы."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(spec.blur)
    shadow.setOffset(0, spec.y_offset)
    shadow.setColor(QColor(*spec.rgba))
    widget.setGraphicsEffect(shadow)
    return shadow


def animate_shadow(
    shadow: QGraphicsDropShadowEffect,
    target: t.ShadowSpec,
    duration_ms: int = t.DURATION_BASE,
) -> QVariantAnimation:
    """Плавный переход тени между уровнями (паттерн lift)."""
    start_blur = shadow.blurRadius()
    start_y = shadow.yOffset()
    start_color = shadow.color()
    end_color = QColor(*target.rgba)

    animation = QVariantAnimation(shadow)
    animation.setDuration(duration_ms)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)

    def _tick(value: float) -> None:
        k = float(value)
        shadow.setBlurRadius(start_blur + (target.blur - start_blur) * k)
        shadow.setOffset(0, start_y + (target.y_offset - start_y) * k)
        shadow.setColor(
            QColor(
                round(start_color.red() + (end_color.red() - start_color.red()) * k),
                round(start_color.green() + (end_color.green() - start_color.green()) * k),
                round(start_color.blue() + (end_color.blue() - start_color.blue()) * k),
                round(start_color.alpha() + (end_color.alpha() - start_color.alpha()) * k),
            )
        )

    animation.valueChanged.connect(_tick)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def fade_in(widget: QWidget, duration_ms: int = t.DURATION_ENTER) -> QVariantAnimation:
    """Появление: прозрачность 0 → 1 (эффект снимается по завершении)."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    animation = QVariantAnimation(widget)
    animation.setDuration(duration_ms)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)

    def _tick(value: float) -> None:
        if shiboken6.isValid(effect):  # эффект мог быть заменён новой анимацией
            effect.setOpacity(float(value))
        else:
            animation.stop()

    def _finish() -> None:
        if shiboken6.isValid(widget) and widget.graphicsEffect() is effect:
            # None допустим в Qt (снять эффект); стабы требуют QGraphicsEffect.
            widget.setGraphicsEffect(None)  # type: ignore[arg-type]

    animation.valueChanged.connect(_tick)
    animation.finished.connect(_finish)
    _restart_entrance(widget, animation)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def materialize(wrapper: QWidget, duration_ms: int = t.DURATION_ENTER) -> QVariantAnimation:
    """Появление новой карточки: fade + «рост» 0.96 → 1.

    Анимируются внутренние поля ОБЁРТКИ (карточка лежит внутри с margins):
    внешняя геометрия не меняется — layout не прыгает.
    """
    start_inset = 10  # ≈ 4% от типовой карточки — визуально scale 0.96 → 1
    effect = QGraphicsOpacityEffect(wrapper)
    effect.setOpacity(0.0)
    wrapper.setGraphicsEffect(effect)

    animation = QVariantAnimation(wrapper)
    animation.setDuration(duration_ms)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)

    layout = wrapper.layout()

    def _tick(value: float) -> None:
        if not shiboken6.isValid(effect):  # эффект заменён следующей анимацией
            animation.stop()
            return
        k = float(value)
        effect.setOpacity(k)
        if layout is not None:
            inset = round(start_inset * (1.0 - k))
            layout.setContentsMargins(inset, inset, inset, inset)

    def _finish() -> None:
        if shiboken6.isValid(wrapper):
            if layout is not None:
                layout.setContentsMargins(0, 0, 0, 0)
            if wrapper.graphicsEffect() is effect:
                wrapper.setGraphicsEffect(None)  # type: ignore[arg-type]

    animation.valueChanged.connect(_tick)
    animation.finished.connect(_finish)
    _restart_entrance(wrapper, animation)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def cascade(
    widgets: Sequence[QWidget],
    *,
    step_ms: int = 45,
    duration_ms: int = t.DURATION_ENTER,
) -> None:
    """Каскадное появление секций: каждая следующая — со сдвигом 30–60 мс.

    Все виджеты мгновенно гаснут (opacity 0), затем по очереди проявляются.
    Если за время задержки виджет умер или его эффект заменила другая
    анимация — отложенный запуск тихо отменяется.
    """
    delay = 0
    for widget in widgets:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        _fade_later(widget, effect, delay_ms=delay, duration_ms=duration_ms)
        delay += step_ms


def _fade_later(
    widget: QWidget, effect: QGraphicsOpacityEffect, *, delay_ms: int, duration_ms: int
) -> None:
    def _start() -> None:
        if not shiboken6.isValid(widget) or widget.graphicsEffect() is not effect:
            return  # виджет умер или эффект уже заменила другая анимация
        animation = QVariantAnimation(widget)
        animation.setDuration(duration_ms)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)

        def _tick(value: float) -> None:
            if shiboken6.isValid(effect):
                effect.setOpacity(float(value))
            else:
                animation.stop()

        def _finish() -> None:
            if shiboken6.isValid(widget) and widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)  # type: ignore[arg-type]

        animation.valueChanged.connect(_tick)
        animation.finished.connect(_finish)
        _restart_entrance(widget, animation)
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    QTimer.singleShot(delay_ms, _start)


def enter_page(page: QWidget, duration_ms: int = t.DURATION_BASE) -> QVariantAnimation:
    """Переход раздела: fade + «подъезд» контента снизу на 12 px.

    Анимируются поля собственного layout'а страницы — внешняя геометрия
    не меняется, стек страниц не прыгает.
    """
    layout = page.layout()
    if layout is None:
        return fade_in(page, duration_ms)
    margins = layout.contentsMargins()
    shift = 12

    effect = QGraphicsOpacityEffect(page)
    effect.setOpacity(0.0)
    page.setGraphicsEffect(effect)

    animation = QVariantAnimation(page)
    animation.setDuration(duration_ms)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)

    def _tick(value: float) -> None:
        if not shiboken6.isValid(effect):
            animation.stop()
            return
        k = float(value)
        effect.setOpacity(k)
        offset = round(shift * (1.0 - k))
        layout.setContentsMargins(
            margins.left(),
            margins.top() + offset,
            margins.right(),
            max(0, margins.bottom() - offset),
        )

    def _finish() -> None:
        if shiboken6.isValid(page):
            layout.setContentsMargins(margins)
            if page.graphicsEffect() is effect:
                page.setGraphicsEffect(None)  # type: ignore[arg-type]

    animation.valueChanged.connect(_tick)
    animation.finished.connect(_finish)
    _restart_entrance(page, animation)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def breathing(widget: QWidget, *, duration_ms: int = t.DURATION_PULSE) -> QVariantAnimation:
    """НЕзапущенный бесконечный цикл 0 → 1 → 0 для «дышащих» акцентов.

    Владелец стартует/останавливает его в show/hideEvent — скрытый виджет
    не должен жечь кадры.
    """
    animation = QVariantAnimation(widget)
    animation.setDuration(duration_ms)
    animation.setLoopCount(-1)
    animation.setStartValue(0.0)
    animation.setKeyValueAt(0.5, 1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.Type.InOutSine)
    return animation


def reveal_scrollbar_on_scroll(area: QAbstractScrollArea, *, linger_ms: int = 900) -> None:
    """macOS-скроллбар: невидим в покое, проявляется на время прокрутки.

    Ставит динамическое свойство ``revealed`` (его читает глобальный QSS)
    и гасит его через ``linger_ms`` после последнего движения.
    """
    bar = area.verticalScrollBar()
    timer = QTimer(bar)
    timer.setSingleShot(True)
    timer.setInterval(linger_ms)

    def _repolish() -> None:
        style = bar.style()
        style.unpolish(bar)
        style.polish(bar)

    def _reveal(_value: int) -> None:
        if not bar.property("revealed"):
            bar.setProperty("revealed", True)
            _repolish()
        timer.start()

    def _conceal() -> None:
        bar.setProperty("revealed", False)
        _repolish()

    bar.valueChanged.connect(_reveal)
    timer.timeout.connect(_conceal)


def count_up(
    label: QLabel,
    target: int,
    *,
    formatter: Callable[[int], str] = str,
    duration_ms: int = t.DURATION_COUNT,
) -> QVariantAnimation:
    """Набегающая цифра: 0 → target с форматированием на каждом кадре."""
    animation = QVariantAnimation(label)
    animation.setDuration(duration_ms)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(0)
    animation.setEndValue(target)
    animation.valueChanged.connect(lambda value: label.setText(formatter(int(value))))
    animation.finished.connect(lambda: label.setText(formatter(target)))
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation
