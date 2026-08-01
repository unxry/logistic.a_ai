"""Главное окно LogistAI — премиальный shell (Stage 9).

Сайдбар-стекло + стек страниц + статус-бар + тосты + палитра ⌘K.
MVVM: окно знает ТОЛЬКО ViewModel'и и UI-события (через UiEventBridge) —
ни сервисов, ни контейнера, ни домена.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import replace
from functools import partial

from PySide6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.clock import utc_now
from app.core.commands import FavoriteCargo, IgnoreCargo, SaveSettings
from app.core.events import SettingsChanged
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.settings import AppSettings, Theme, UISettings, VehicleSettings
from app.ui.bridge import UiEventBridge
from app.ui.pages import (
    AnalyticsPage,
    CargoPage,
    DashboardPage,
    FavoritesPage,
    NotificationHistoryPage,
    Page,
    SearchPage,
    SettingsPage,
    SourcesPage,
    VehiclePage,
)
from app.ui.theme import build_global_qss, enter_page
from app.ui.theme import tokens as t
from app.ui.theme.manager import ThemeManager
from app.ui.viewmodels import (
    BadgeTone,
    CargoCardViewModel,
    CommandDispatcher,
    DashboardSnapshot,
    DashboardViewModel,
    EventStream,
    SourceStatusViewModel,
)
from app.ui.viewmodels.main_viewmodel import MainViewModel
from app.ui.widgets import (
    Badge,
    Command,
    CommandPalette,
    Modal,
    Sidebar,
    ToastHost,
    build_explanation_panel,
)


class MainWindow(QMainWindow):
    """Окно-оболочка приложения."""

    def __init__(
        self,
        view_model: MainViewModel,
        dashboard: DashboardViewModel,
        events: EventStream,
        *,
        command_dispatcher: CommandDispatcher | None = None,
        current_settings: AppSettings | None = None,
        theme_manager: ThemeManager | None = None,
        background_on_close: bool = False,
        demo: bool = False,
        extra_commands: Sequence[Command] = (),
    ) -> None:
        super().__init__()
        self._view_model = view_model
        self._dashboard = dashboard
        self._commands = command_dispatcher
        self._settings = current_settings if current_settings is not None else AppSettings()
        self._theme_manager = theme_manager
        self._background_on_close = background_on_close
        self._tasks: set[asyncio.Task[object]] = set()

        self.setWindowTitle(view_model.window_title)
        self.resize(t.WINDOW_DEFAULT_W, t.WINDOW_DEFAULT_H)
        self.setMinimumSize(t.WINDOW_MIN_W, t.WINDOW_MIN_H)
        self.setStyleSheet(build_global_qss())

        root = QWidget(self)
        root.setObjectName("AppRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = Sidebar(view_model.status_line, root)
        self.sidebar.navigated.connect(self.show_page)
        root_layout.addWidget(self.sidebar)

        content = QWidget(root)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        root_layout.addWidget(content, stretch=1)

        self.pages = QStackedWidget(content)
        content_layout.addWidget(self.pages, stretch=1)

        self.dashboard_page = DashboardPage(
            on_explain=self._explain_cargo, on_ignore=self._ignore_cargo, demo=demo
        )
        self._pages: dict[str, Page] = {}
        for page in (
            self.dashboard_page,
            CargoPage(
                on_explain=self._explain_cargo,
                on_favorite=self._favorite_cargo,
                on_ignore=self._ignore_cargo,
            ),
            FavoritesPage(on_explain=self._explain_cargo, on_ignore=self._ignore_cargo),
            VehiclePage(
                on_create=self._create_vehicle,
                on_edit=self._edit_vehicle,
                on_duplicate=self._duplicate_vehicle,
                on_delete=self._delete_vehicle,
            ),
            SearchPage(),
            AnalyticsPage(demo=demo),
            NotificationHistoryPage(),
            SourcesPage(),
            SettingsPage(
                current_theme=self._settings.ui.theme,
                on_theme_changed=self._change_theme,
            ),
        ):
            self._pages[page.page_id] = page
            self.pages.addWidget(page)

        self._build_status_bar()

        # Оверлеи поверх окна.
        self.toasts = ToastHost(self)
        self.modal = Modal(self)
        # Имя command_palette: не затеняет QWidget.palette().
        self.command_palette = CommandPalette(self)
        self.command_palette.set_commands(self._build_commands(extra_commands))

        # Мост UI-событий и горячие клавиши.
        self._bridge = UiEventBridge(events, self)
        self._bridge.dashboard_updated.connect(self._on_dashboard_updated)
        self._bridge.recommendations_changed.connect(self._on_recommendations)
        self._bridge.source_changed.connect(self._on_source_changed)
        events.subscribe(SettingsChanged, self._on_settings_changed)
        self._events = events
        self._install_shortcuts()

    def set_theme_manager(self, theme_manager: ThemeManager) -> None:
        """Attach live ThemeManager after the root window exists."""
        self._theme_manager = theme_manager

    # ── Навигация и команды ───────────────────────────────────────────────────

    def show_page(self, page_id: str) -> None:
        """Открыть раздел приложения (переход — fade + подъезд контента)."""
        page = self._pages.get(page_id)
        if page is None:
            return
        switched = self.pages.currentWidget() is not page
        self.pages.setCurrentWidget(page)
        self.sidebar.select(page_id)
        if switched and self.isVisible():
            enter_page(page)

    def current_page_id(self) -> str:
        """Идентификатор открытого раздела."""
        widget = self.pages.currentWidget()
        return widget.page_id if isinstance(widget, Page) else ""

    def open_palette(self) -> None:
        """Показать палитру команд (⌘K)."""
        self.command_palette.open_palette()

    def refresh_dashboard(self) -> None:
        """Запросить обновление данных (⌘R)."""
        self._schedule(self._dashboard.refresh())

    def _build_commands(self, extra: Sequence[Command]) -> tuple[Command, ...]:
        titles = {
            "dashboard": ("Открыть Dashboard", "🚚"),
            "cargo": ("Найти груз", "📦"),
            "favorites": ("Открыть избранное", "⭐"),
            "vehicle": ("Открыть машину", "🚗"),
            "search": ("Запустить поиск", "🔍"),
            "analytics": ("Открыть аналитику", "📊"),
            "notifications": ("История уведомлений", "🕘"),
            "sources": ("Открыть источники", "🔌"),
            "settings": ("Открыть настройки", "⚙️"),
        }
        navigation = tuple(
            Command(
                id=f"go-{page_id}",
                title=titles.get(page_id, (page_id, ""))[0],
                subtitle="Навигация",
                shortcut=f"⌘{index + 1}",
                icon=titles.get(page_id, (page_id, "•"))[1],
                run=partial(self.show_page, page_id),
                keywords=(page_id,),
            )
            for index, page_id in enumerate(self._pages)
        )
        actions = (
            Command(
                id="refresh",
                title="Обновить данные",
                subtitle="Перечитать источники, аналитику и журнал",
                shortcut="⌘R",
                icon="🔄",
                run=self.refresh_dashboard,
                keywords=("refresh", "обновить"),
            ),
        )
        return (*navigation, *actions, *tuple(extra))

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, self.open_palette)
        QShortcut(QKeySequence("Ctrl+R"), self, self.refresh_dashboard)
        for index, page_id in enumerate(self._pages):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self, partial(self.show_page, page_id))

    # ── Реакции на UI-события ─────────────────────────────────────────────────

    def _on_dashboard_updated(self, snapshot: DashboardSnapshot) -> None:
        self._status_app.set_badge(snapshot.application_status)
        self._status_telegram.set_badge(snapshot.telegram_status)
        self.sidebar.set_ai_tone(snapshot.application_status.tone)
        ati_tone = next(
            (s.status.tone for s in snapshot.sources_status if s.id == "ati"),
            BadgeTone.MUTED,
        )
        self.sidebar.set_link_tones(
            snapshot.telegram_status.tone, ati_tone, snapshot.application_status.tone
        )
        for page in self._pages.values():
            page.apply_snapshot(snapshot)

    def _on_recommendations(self, cards: tuple[CargoCardViewModel, ...]) -> None:
        self.dashboard_page.show_recommendations(cards)
        if cards:
            self.toasts.show_toast(
                "Найден новый лучший груз",
                f"{cards[0].route} · {cards[0].profit} чистыми",
                BadgeTone.OK,
            )

    def _on_source_changed(self, source: SourceStatusViewModel) -> None:
        self.dashboard_page.update_source(source)
        if source.status.tone is BadgeTone.ERROR:
            self.toasts.show_toast(
                f"{source.name} недоступен",
                source.errors or "Источник перестал отвечать",
                BadgeTone.ERROR,
            )

    # ── AI Explanation / Hero действия ───────────────────────────────────────

    def _explain_cargo(self, card: CargoCardViewModel) -> None:
        panel = build_explanation_panel(card, self.modal)
        self.modal.show_content("Почему выбран этот груз", panel)

    def _ignore_cargo(self, cargo_id: str) -> None:
        async def _ignore() -> None:
            if self._commands is not None:
                await self._commands.dispatch(IgnoreCargo(cargo_id=cargo_id))
            remaining = tuple(
                card for card in self._dashboard.best_matches if card.cargo_id != cargo_id
            )
            self._dashboard.set_recommendation_cards(remaining)
            self.toasts.show_toast(
                "Груз скрыт", "Если условия изменятся, AI покажет его снова", BadgeTone.MUTED
            )

        self._schedule(_ignore())

    def _favorite_cargo(self, cargo_id: str) -> None:
        async def _favorite() -> None:
            if self._commands is not None:
                await self._commands.dispatch(FavoriteCargo(cargo_id=cargo_id))
            await self._dashboard.refresh()
            self.toasts.show_toast(
                "Груз сохранён", "Он останется в разделе «Избранное»", BadgeTone.OK
            )

        self._schedule(_favorite())

    def _change_theme(self, theme: Theme) -> None:
        """Save theme via CommandBus, then apply it live."""
        new_settings = replace(
            self._settings, ui=UISettings(theme=theme, autostart=self._settings.ui.autostart)
        )
        if self._theme_manager is not None:
            self._theme_manager.apply(theme)
        self._schedule(self._save_settings(new_settings))

    async def _save_settings(self, settings: AppSettings) -> None:
        if self._commands is not None:
            await self._commands.dispatch(SaveSettings(settings=settings))
        self._settings = settings
        await self._dashboard.refresh()

    def _create_vehicle(self) -> None:
        profile = VehicleProfile.create(
            name="MAN TGL 12т",
            vehicle_type=VehicleType.TRUCK,
            body_type=BodyType.TENT,
            cargo_capacity_kg=6000,
            length_cm=620,
            width_cm=245,
            height_cm=250,
            volume_m3=38.0,
            pallet_capacity=14,
            max_weight_kg=12000,
            allowed_regions=("RU",),
        )
        vehicle = VehicleSettings(
            profiles=(*self._settings.vehicle.profiles, profile), active_profile_id=profile.id
        )
        self._schedule(self._save_settings(replace(self._settings, vehicle=vehicle)))
        self.toasts.show_toast(
            "Машина создана", "AI Matching начнёт использовать новый профиль", BadgeTone.OK
        )

    def _edit_vehicle(self) -> None:
        active = self._settings.vehicle.active_profile()
        if active is None:
            self._create_vehicle()
            return
        edited = replace(active, name=f"{active.name} · обновлено", updated_at=utc_now())
        profiles = tuple(
            edited if item.id == active.id else item for item in self._settings.vehicle.profiles
        )
        self._schedule(
            self._save_settings(
                replace(self._settings, vehicle=replace(self._settings.vehicle, profiles=profiles))
            )
        )
        self.toasts.show_toast(
            "Машина обновлена", "Рекомендации будут пересчитаны с новым профилем", BadgeTone.OK
        )

    def _duplicate_vehicle(self) -> None:
        active = self._settings.vehicle.active_profile()
        if active is None:
            self._create_vehicle()
            return
        duplicate = VehicleProfile.create(
            name=f"{active.name} · копия",
            vehicle_type=active.vehicle_type,
            body_type=active.body_type,
            cargo_capacity_kg=active.cargo_capacity_kg,
            length_cm=active.length_cm,
            width_cm=active.width_cm,
            height_cm=active.height_cm,
            volume_m3=active.volume_m3,
            pallet_capacity=active.pallet_capacity,
            max_weight_kg=active.max_weight_kg,
            allowed_regions=active.allowed_regions,
            empty_weight_kg=active.empty_weight_kg,
            axle_weight_kg=active.axle_weight_kg,
            vehicle_permits=active.vehicle_permits,
            has_trailer=active.has_trailer,
            eco_class=active.eco_class,
        )
        vehicle = VehicleSettings(
            profiles=(*self._settings.vehicle.profiles, duplicate), active_profile_id=duplicate.id
        )
        self._schedule(self._save_settings(replace(self._settings, vehicle=vehicle)))
        self.toasts.show_toast("Машина продублирована", duplicate.name, BadgeTone.OK)

    def _delete_vehicle(self) -> None:
        active = self._settings.vehicle.active_profile()
        if active is None:
            return
        profiles = tuple(item for item in self._settings.vehicle.profiles if item.id != active.id)
        next_active = profiles[0].id if profiles else None
        vehicle = VehicleSettings(profiles=profiles, active_profile_id=next_active)
        self._schedule(self._save_settings(replace(self._settings, vehicle=vehicle)))
        self.toasts.show_toast(
            "Машина удалена", "Undo появится после журнала действий", BadgeTone.WARNING
        )

    # ── Служебное ─────────────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self._status_app = Badge(parent=self)
        self._status_telegram = Badge(parent=self)
        telegram_caption = QLabel("Telegram:", self)
        telegram_caption.setStyleSheet(
            f"QLabel {{ color: {t.TEXT_TERTIARY}; font-size: {t.CAPTION_PT}pt; }}"
        )
        bar.addWidget(self._status_app)
        bar.addWidget(telegram_caption)
        bar.addWidget(self._status_telegram)

    def _schedule(self, coroutine: Coroutine[object, object, object]) -> None:
        """Запустить корутину: в петле qasync — задачей, в тестах — синхронно."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coroutine)
            return
        task = loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API)
        """Оверлеи следуют за размером окна."""
        super().resizeEvent(event)
        self.toasts.relayout()
        for overlay in (self.modal, self.command_palette):
            if overlay.isVisible():
                overlay.setGeometry(self.rect())

    def closeEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        """Отписаться от шины при закрытии."""
        if self._background_on_close:
            self.hide()
            ignore = getattr(event, "ignore", None)
            if callable(ignore):
                ignore()
            return
        self._bridge.detach()
        self._events.unsubscribe(SettingsChanged, self._on_settings_changed)
        super().closeEvent(event)  # type: ignore[arg-type]

    def _on_settings_changed(self, event: SettingsChanged) -> None:
        self._settings = event.settings
