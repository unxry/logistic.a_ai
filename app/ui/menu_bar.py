"""macOS Menu Bar / System Tray контроллер LogistAI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.core.commands import PauseJob, RunJobNow
from app.ui.viewmodels import (
    BadgeTone,
    CargoRecommendationChanged,
    CommandDispatcher,
    DashboardSnapshot,
    DashboardUpdated,
    EventStream,
)


class MenuBarController(QObject):
    """Menu Bar иконка: read-model из DashboardSnapshot, мутации через CommandBus."""

    def __init__(
        self,
        *,
        window: object,
        events: EventStream,
        commands: CommandDispatcher,
        quit_requested: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._events = events
        self._commands = commands
        self._quit_requested = quit_requested
        self._snapshot: DashboardSnapshot | None = None
        self._pulse = 0
        self._attached = False

        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("LogistAI")
        self._tray.setIcon(self._icon(BadgeTone.MUTED))
        self._menu = QMenu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._animation = QTimer(self)
        self._animation.setInterval(220)
        self._animation.timeout.connect(self._animate_best_cargo)
        self._rebuild_menu()

    def attach(self) -> None:
        """Подписаться на события и показать иконку."""
        if self._attached:
            return
        self._events.subscribe(DashboardUpdated, self._on_dashboard_updated)
        self._events.subscribe(CargoRecommendationChanged, self._on_recommendations)
        self._tray.show()
        self._attached = True

    def detach(self) -> None:
        """Отписаться и спрятать иконку."""
        self._animation.stop()
        if self._attached:
            self._events.unsubscribe(DashboardUpdated, self._on_dashboard_updated)
            self._events.unsubscribe(CargoRecommendationChanged, self._on_recommendations)
            self._attached = False
        self._tray.hide()

    def _on_dashboard_updated(self, event: DashboardUpdated) -> None:
        self._snapshot = event.snapshot
        self._tray.setIcon(self._icon(event.snapshot.application_status.tone))
        self._rebuild_menu()

    def _on_recommendations(self, event: CargoRecommendationChanged) -> None:
        if event.cards:
            self._pulse = 0
            self._animation.start()

    def _animate_best_cargo(self) -> None:
        self._pulse += 1
        tone = BadgeTone.OK if self._pulse % 2 else BadgeTone.WARNING
        self._tray.setIcon(self._icon(tone))
        if self._pulse >= 8:
            self._animation.stop()
            tone = (
                self._snapshot.application_status.tone
                if self._snapshot is not None
                else BadgeTone.MUTED
            )
            self._tray.setIcon(self._icon(tone))

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        snapshot = self._snapshot
        if snapshot is None:
            self._menu.addAction("LogistAI запускается…")
        else:
            ati = next((source for source in snapshot.sources_status if source.id == "ati"), None)
            best = snapshot.best_matches[0] if snapshot.best_matches else None
            self._menu.addAction(f"ATI: {ati.status.label if ati is not None else '—'}")
            self._menu.addAction(f"Найдено сегодня: {snapshot.analytics_summary.today_found}")
            self._menu.addAction(f"Лучший груз: {best.route if best is not None else '—'}")
            self._menu.addAction(
                f"Потенциальная прибыль: {snapshot.analytics_summary.potential_profit}"
            )
            self._menu.addAction(
                f"Последняя синхронизация: {ati.last_sync if ati is not None else '—'}"
            )
        self._menu.addSeparator()
        self._menu.addAction(self._action("Открыть Dashboard", self._open_dashboard))
        self._menu.addAction(self._action("Искать сейчас", self._search_now))
        self._menu.addAction(self._action("Пауза", self._pause_ati))
        self._menu.addAction(self._action("Настройки", self._open_settings))
        self._menu.addSeparator()
        self._menu.addAction(self._action("Выход", self._quit))

    def _action(self, title: str, callback: object) -> QAction:
        action = QAction(title, self._menu)
        action.triggered.connect(callback)
        return action

    def _open_dashboard(self) -> None:
        self._show_window("dashboard")

    def _open_settings(self) -> None:
        self._show_window("settings")

    def _show_window(self, page_id: str) -> None:
        show_page = getattr(self._window, "show_page", None)
        show = getattr(self._window, "show", None)
        raise_ = getattr(self._window, "raise_", None)
        activate = getattr(self._window, "activateWindow", None)
        if callable(show_page):
            show_page(page_id)
        if callable(show):
            show()
        if callable(raise_):
            raise_()
        if callable(activate):
            activate()

    def _search_now(self) -> None:
        self._schedule(self._commands.dispatch(RunJobNow(job_name="source:ati")))

    def _pause_ati(self) -> None:
        self._schedule(self._commands.dispatch(PauseJob(job_name="source:ati")))

    def _quit(self) -> None:
        if self._quit_requested is not None:
            self._quit_requested()
        else:
            QApplication.quit()

    def _schedule(self, coroutine: Coroutine[object, object, object]) -> None:
        try:
            asyncio.get_running_loop().create_task(coroutine)
        except RuntimeError:
            asyncio.run(coroutine)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.Trigger:
            self._open_dashboard()

    @staticmethod
    def _icon(tone: BadgeTone) -> QIcon:
        colors = {
            BadgeTone.OK: "#30D158",
            BadgeTone.WARNING: "#FF9F0A",
            BadgeTone.ERROR: "#FF453A",
            BadgeTone.MUTED: "#8E8E93",
        }
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors[tone]))
        painter.setPen(QColor(255, 255, 255, 190))
        painter.drawEllipse(6, 6, 20, 20)
        painter.end()
        return QIcon(pixmap)
