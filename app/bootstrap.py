"""Composition root: сборка зависимостей и запуск приложения.

Stage 9/9.5: единая петля qasync (ADR-0003), премиальный shell, старт
Scheduler'а при запуске (ATI-POLL и мониторинг здоровья работают сами).
Флаги: ``--demo`` — дашборд на мок-данных; ``--demo-ati`` — РЕАЛЬНЫЙ
конвейер ATI на мок-транспорте (auth → пагинация → нормализация → дедуп →
подбор → уведомление → дашборд) без внешней сети и без секретов.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from decimal import Decimal

from app.buses import CommandBus, EventBus
from app.container import AppContainer
from app.core.commands import (
    FavoriteCargo,
    IgnoreCargo,
    PauseJob,
    ResumeJob,
    RunJobNow,
    SaveSettings,
    SendNotification,
    SendTestMessage,
    StartScheduler,
    StopScheduler,
    TransitionCargoWorkflow,
    VerifyTelegram,
)
from app.core.events import AppStarted
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.routes import RouteCachePolicy, RouteRequest, RouteVehicleParameters
from app.core.ports.secret_store import YANDEX_ROUTER_API_KEY_KEY
from app.core.ports.source_credentials import CRED_API_KEY
from app.infrastructure.logging.setup import setup_logging
from app.infrastructure.notifications.macos import MacOSNotificationChannel
from app.infrastructure.routes import (
    CachedGeocodingProvider,
    CompositeRouteProvider,
    FallbackGeocodingProvider,
    MockRouteProvider,
    OsrmRouteProvider,
    OsrmRoutesClient,
    StaticGeocodingProvider,
    YandexGeocodingProvider,
    YandexRoutesClient,
    YandexTruckRouteProvider,
)
from app.infrastructure.settings.json_repository import JsonSettingsRepository
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.sources.ati import AtiClient, AtiSource
from app.infrastructure.sources.config_repository import JsonSourceConfigurationRepository
from app.infrastructure.sources.credentials import KeychainSourceCredentialProvider
from app.infrastructure.storage.cargo_repository import SqliteCargoRepository
from app.infrastructure.storage.database import Database
from app.infrastructure.storage.history_repository import SqliteHistoryRepository
from app.infrastructure.storage.matching_repository import SqliteMatchingRepository
from app.infrastructure.storage.notification_history_repository import (
    SqliteNotificationHistoryRepository,
)
from app.infrastructure.storage.route_cache_repository import SqliteRouteCacheRepository
from app.infrastructure.system.autostart import MacOSLaunchAgentAutostart
from app.infrastructure.system.build_info import load_build_info
from app.infrastructure.system.paths import PlatformPaths
from app.infrastructure.telegram.client import TelegramClient
from app.infrastructure.telegram.formatting import TelegramNotificationFormatter
from app.runtime import ShutdownCoordinator
from app.services.logistics import (
    CargoCompatibilityService,
    CargoWorkflowService,
    FavoriteCargoHandler,
    IgnoreCargoHandler,
    TransitionCargoWorkflowHandler,
)
from app.services.matching import (
    CargoProfitCalculator,
    IntelligentMatchingService,
    PreferenceEngine,
    RouteScoreCalculator,
)
from app.services.monitoring import (
    AnalyticsCollector,
    DailyAnalyticsReportJob,
    DecisionPersister,
    RouteAvailabilityNotifier,
    RouteMetricsCollector,
    SourceHealthCheckJob,
    SourceHealthMonitor,
)
from app.services.notifications import (
    ChannelRegistry,
    FormatterRegistry,
    NotificationDispatcher,
    NotificationRouter,
    NotificationService,
    PlainTextFormatter,
    SendNotificationHandler,
)
from app.services.presentation import DashboardDataService
from app.services.routes import RouteCostCalculator, RouteService
from app.services.scheduler import (
    HistoryCleanupJob,
    JobRegistry,
    PauseJobHandler,
    ResumeJobHandler,
    RunJobNowHandler,
    SchedulerRuntime,
    StartSchedulerHandler,
    StopSchedulerHandler,
)
from app.services.search import (
    CargoMatchingService,
    CargoPreFilter,
    CargoRankingService,
    CargoScoreCalculator,
    CargoSearchEngine,
    RecommendationPipeline,
)
from app.services.settings_service import SaveSettingsHandler, SettingsService
from app.services.sources import (
    CargoDeduplicationService,
    CargoNormalizer,
    SourceRegistry,
    SourceRuntime,
)
from app.services.telegram import (
    SendTestMessageHandler,
    TelegramBotService,
    TelegramCommandRouter,
    TelegramService,
    VerifyTelegramHandler,
)
from app.ui.viewmodels import DashboardViewModel

logger = logging.getLogger(__name__)

APP_NAME = "LogistAI"
ORGANIZATION_DOMAIN = "logistai.app"
SETTINGS_FILENAME = "settings.json"
DATABASE_FILENAME = "logistai.db"


def build_container(
    *,
    demo_dashboard: bool = False,
    demo_ati: bool = False,
    demo_routes: bool = False,
) -> AppContainer:
    """Собрать все зависимости приложения.

    Порядок: пути → шины → логирование → настройки/секреты → хранилище →
    Telegram → Notification Center → источники → поиск/подбор → мониторинг →
    presentation → пайплайн → команды. ``demo_dashboard`` подменяет данные
    дашборда мок-провайдером; ``demo_ati`` подменяет ТОЛЬКО транспорт ATI и
    конфигурацию источника (весь конвейер — боевой, секретов нет).
    """
    paths = PlatformPaths()
    event_bus = EventBus()
    command_bus = CommandBus()
    log_buffer = setup_logging(paths.logs_dir, event_bus=event_bus)

    settings_repository = JsonSettingsRepository(paths.config_dir / SETTINGS_FILENAME)
    secret_store = KeyringSecretStore()
    settings_service = SettingsService(
        repository=settings_repository,
        secret_store=secret_store,
        event_bus=event_bus,
    )
    settings_service.load()

    database = Database(paths.data_dir / DATABASE_FILENAME)
    database.connect()
    history_repository = SqliteHistoryRepository(database)
    notification_history_repository = SqliteNotificationHistoryRepository(database)

    telegram_service = TelegramService(
        api_factory=TelegramClient,
        formatter=TelegramNotificationFormatter(),
        event_bus=event_bus,
        token_provider=settings_service.get_bot_token,
        chat_id_provider=settings_service.get_chat_id,
    )

    # Notification Center: каналы и форматтеры регистрируются ОДИН раз здесь
    # (позже сюда же добавят вклады плагины через PluginExtensions).
    channels = ChannelRegistry()
    channels.register(telegram_service)
    channels.register(MacOSNotificationChannel())

    formatters = FormatterRegistry(default=PlainTextFormatter())
    formatters.register(telegram_service.channel_id, TelegramNotificationFormatter())

    notification_service = NotificationService(
        router=NotificationRouter(lambda: settings_service.current.notifications.enabled_channels),
        dispatcher=NotificationDispatcher(channels, formatters),
        history=history_repository,
        event_bus=event_bus,
        notification_history=notification_history_repository,
    )

    # Платформа источников: пользователь настраивает их конфигурациями
    # (sources.json + секреты в Keychain), а не кодом. ATI поставляется
    # выключенным (enabled=False в spec) — оживает только конфигурацией.
    # В demo-ati подменяются транспорт, учётки и конфигурация — конвейер боевой.
    if demo_ati:
        from app.infrastructure.sources.ati.demo import (
            DemoAtiConfigurationRepository,
            build_demo_ati_client,
        )

        ati_client, _demo_api = build_demo_ati_client()
        source_configurations: JsonSourceConfigurationRepository | DemoAtiConfigurationRepository
        source_configurations = DemoAtiConfigurationRepository()
        source_credentials = KeychainSourceCredentialProvider(secret_store)
    else:
        source_configurations = JsonSourceConfigurationRepository(paths.config_dir / "sources.json")
        source_credentials = KeychainSourceCredentialProvider(secret_store)
        ati_client = AtiClient(source_credentials)
    source_registry = SourceRegistry(event_bus)
    source_registry.register(AtiSource(source_credentials, client=ati_client))
    source_runtime = SourceRuntime(
        registry=source_registry,
        normalizer=CargoNormalizer(),
        event_bus=event_bus,
        notifications=notification_service,
        history=history_repository,
        settings_provider=lambda: settings_service.current,
        configurations=source_configurations,
        duplicates_provider=lambda source_id: analytics_collector.duplicate_counts[source_id],
    )

    # Search Engine: чистый пайплайн подбора + оркестрация с событиями и NC.
    cargo_repository = SqliteCargoRepository(database)
    matching_service = CargoMatchingService(
        engine=CargoSearchEngine(
            prefilter=CargoPreFilter(),
            compatibility=CargoCompatibilityService(BasicCompatibilityChecker()),
            scorer=CargoScoreCalculator(),
            ranking=CargoRankingService(),
        ),
        repository=cargo_repository,
        event_bus=event_bus,
        notifications=notification_service,
    )

    # Route Intelligence: production chain Yandex Truck → OSRM → cache/mock.
    # Matching и ProfitCalculator видят только порт RouteProvider и RouteEstimate.
    route_cache_repository = SqliteRouteCacheRepository(database)
    route_provider = _build_route_provider(
        settings_service=settings_service,
        secret_store=secret_store,
        source_credentials=source_credentials,
        cache=route_cache_repository,
        event_bus=event_bus,
        demo_routes=demo_routes,
    )
    route_service = RouteService(
        provider=route_provider,
        costs=RouteCostCalculator(settings_service.current.routing),
        event_bus=event_bus,
    )

    # Intelligent Matching: предпочтения + реальная экономика + маршрут + свежесть.
    intelligent_matcher = IntelligentMatchingService(
        preferences=PreferenceEngine(),
        profit=CargoProfitCalculator(),
        routes=route_service,
        route_score=RouteScoreCalculator(),
        event_bus=event_bus,
        notifications=notification_service,
        weights=settings_service.current.matching,
    )
    cargo_workflow_service = CargoWorkflowService(
        repository=cargo_repository,
        history=history_repository,
        events=event_bus,
    )

    # Monitoring & Analytics: решения — в SQLite, счётчики — из событий,
    # здоровье источников — под надзором, ежедневный отчёт — через Scheduler.
    matching_repository = SqliteMatchingRepository(database)
    analytics_collector = AnalyticsCollector()
    analytics_collector.attach(event_bus)
    RouteMetricsCollector().attach(event_bus)
    RouteAvailabilityNotifier(notification_service).attach(event_bus)
    DecisionPersister(matching_repository).attach(event_bus)
    health_monitor = SourceHealthMonitor(
        health_provider=lambda: {
            source_id: source_runtime.health(source_id) for source_id in source_registry.ids()
        },
        notifications=notification_service,
    )

    # Presentation-слой (Stage 8.6/9): read-model дашборда + презентер.
    # В demo-режиме UI живёт на детерминированных данных мок-провайдера.
    live_provider = DashboardDataService(
        telegram=telegram_service,
        settings=settings_service,
        registry=source_registry,
        runtime=source_runtime,
        collector=analytics_collector,
        matching_repository=matching_repository,
        history=history_repository,
        cargos=cargo_repository,
        notification_history=notification_history_repository,
    )
    if demo_dashboard:
        from app.ui.viewmodels import MOCK_NOW, MockDashboardDataProvider

        # Часы демо заморожены на MOCK_NOW: метки «5 мин назад» осмысленны.
        dashboard_viewmodel = DashboardViewModel(
            provider=MockDashboardDataProvider(), events=event_bus, clock=lambda: MOCK_NOW
        )
    else:
        dashboard_viewmodel = DashboardViewModel(provider=live_provider, events=event_bus)
    dashboard_viewmodel.attach()

    # Конвейер рекомендаций (Stage 9.5): CargoReceived → дедуп → хранилище →
    # поиск → интеллектуальный подбор → уведомление → карточки в дашборд.
    if demo_ati:
        from app.ui.viewmodels import mock_vehicle

        demo_vehicle = mock_vehicle()
        pipeline_driver = DriverProfile.create(home_region="Москва")
        pipeline_location = "Москва"

        def vehicle_provider() -> VehicleProfile | None:
            return demo_vehicle
    else:
        pipeline_driver = DriverProfile.create()
        pipeline_location = ""

        def vehicle_provider() -> VehicleProfile | None:
            return settings_service.current.vehicle.active_profile()

    recommendation_pipeline = RecommendationPipeline(
        repository=cargo_repository,
        matching=matching_service,
        intelligent=intelligent_matcher,
        deduplicator=CargoDeduplicationService(),
        vehicle_provider=vehicle_provider,
        driver_provider=lambda: pipeline_driver,
        location_provider=lambda: pipeline_location,
        on_ranked=dashboard_viewmodel.update_recommendations,
        duplicates_sink=analytics_collector.record_duplicates,
        event_publisher=event_bus,
    )
    recommendation_pipeline.attach(event_bus)

    # Scheduler Runtime: задачи регистрируются здесь (позже — и плагинами);
    # start() вызывается командой StartScheduler, когда появится петля qasync.
    job_registry = JobRegistry()
    job_registry.register(HistoryCleanupJob())
    job_registry.register(SourceHealthCheckJob(health_monitor))
    job_registry.register(
        DailyAnalyticsReportJob(
            matching_repository=matching_repository,
            collector=analytics_collector,
            health_provider=lambda: {
                source_id: source_runtime.health(source_id) for source_id in source_registry.ids()
            },
        )
    )
    for source_job in source_runtime.build_jobs():
        job_registry.register(source_job)
    scheduler = SchedulerRuntime(
        registry=job_registry,
        event_bus=event_bus,
        notifications=notification_service,
        history=history_repository,
        settings_provider=lambda: settings_service.current,
    )

    # Production Telegram-бот (Stage 9.7): роутер команд собирается здесь —
    # данные из сервисов, тексты из infrastructure/telegram/bot_replies.
    telegram_bot = _build_telegram_bot(
        settings_service=settings_service,
        command_bus=command_bus,
        pipeline=recommendation_pipeline,
        collector=analytics_collector,
        source_registry=source_registry,
        source_runtime=source_runtime,
        source_configurations=source_configurations,
        matching_repository=matching_repository,
        cargo_repository=cargo_repository,
        scheduler=scheduler,
        dashboard=dashboard_viewmodel,
        driver=pipeline_driver,
        build_version=load_build_info().version,
    )

    command_bus.register(SaveSettings, SaveSettingsHandler(settings_service))
    command_bus.register(VerifyTelegram, VerifyTelegramHandler(telegram_service))
    command_bus.register(SendTestMessage, SendTestMessageHandler(telegram_service))
    command_bus.register(SendNotification, SendNotificationHandler(notification_service))
    command_bus.register(
        TransitionCargoWorkflow,
        TransitionCargoWorkflowHandler(cargo_workflow_service),
    )
    command_bus.register(FavoriteCargo, FavoriteCargoHandler(cargo_workflow_service))
    command_bus.register(IgnoreCargo, IgnoreCargoHandler(cargo_workflow_service))
    command_bus.register(StartScheduler, StartSchedulerHandler(scheduler))
    command_bus.register(StopScheduler, StopSchedulerHandler(scheduler))
    command_bus.register(PauseJob, PauseJobHandler(scheduler))
    command_bus.register(ResumeJob, ResumeJobHandler(scheduler))
    command_bus.register(RunJobNow, RunJobNowHandler(scheduler))

    return AppContainer(
        build_info=load_build_info(),
        event_bus=event_bus,
        command_bus=command_bus,
        path_provider=paths,
        settings_service=settings_service,
        telegram_service=telegram_service,
        notification_service=notification_service,
        job_registry=job_registry,
        scheduler=scheduler,
        source_registry=source_registry,
        source_runtime=source_runtime,
        cargo_repository=cargo_repository,
        matching_service=matching_service,
        recommendation_pipeline=recommendation_pipeline,
        ati_client=ati_client,
        route_service=route_service,
        intelligent_matcher=intelligent_matcher,
        matching_repository=matching_repository,
        analytics_collector=analytics_collector,
        health_monitor=health_monitor,
        dashboard_viewmodel=dashboard_viewmodel,
        telegram_bot=telegram_bot,
        history_repository=history_repository,
        notification_history_repository=notification_history_repository,
        database=database,
        log_buffer=log_buffer,
    )


def _build_route_provider(
    *,
    settings_service: SettingsService,
    secret_store: KeyringSecretStore,
    source_credentials: KeychainSourceCredentialProvider,
    cache: SqliteRouteCacheRepository,
    event_bus: EventBus,
    demo_routes: bool,
) -> CompositeRouteProvider:
    """Production route chain: Yandex Truck → OSRM → Mock, with SQLite cache."""
    routing = settings_service.current.routing

    def yandex_api_key() -> str | None:
        return secret_store.get(YANDEX_ROUTER_API_KEY_KEY) or source_credentials.get(
            routing.yandex_credentials_reference, CRED_API_KEY
        )

    static_geocoder = StaticGeocodingProvider()
    if demo_routes:
        geocoder = CachedGeocodingProvider(
            inner=static_geocoder,
            cache=cache,
            policy=RouteCachePolicy(),
        )
        yandex_client = _demo_yandex_routes_client()
    else:
        live_geocoder = YandexGeocodingProvider(api_key_provider=yandex_api_key)
        geocoder = CachedGeocodingProvider(
            inner=FallbackGeocodingProvider((live_geocoder, static_geocoder)),
            cache=cache,
            policy=RouteCachePolicy(),
        )
        yandex_client = YandexRoutesClient(api_key_provider=yandex_api_key)

    return CompositeRouteProvider(
        yandex=YandexTruckRouteProvider(client=yandex_client, geocoder=geocoder),
        osrm=OsrmRouteProvider(
            client=OsrmRoutesClient(base_url=routing.osrm_base_url),
            geocoder=geocoder,
        ),
        mock=MockRouteProvider(),
        geocoder=geocoder,
        cache=cache,
        events=event_bus,
        cache_policy=RouteCachePolicy(),
        provider_choice=routing.provider,
        cache_enabled=routing.cache_enabled,
        fallback_enabled=routing.fallback_enabled,
    )


def _demo_yandex_routes_client() -> YandexRoutesClient:
    """Yandex client on MockTransport for deterministic --demo-routes."""
    import httpx

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "traffic_type": "forecast",
                "route": {
                    "legs": [
                        {
                            "steps": [
                                {
                                    "length": 726_000,
                                    "duration": 36_720,
                                    "polyline": {
                                        "points": [
                                            [55.755864, 37.617698],
                                            [55.796127, 49.106414],
                                        ]
                                    },
                                }
                            ]
                        }
                    ],
                    "flags": {"hasTolls": True},
                },
            },
        )

    return YandexRoutesClient(
        api_key_provider=lambda: "demo-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def _run_routes_smoke(container: AppContainer) -> None:
    """Demo route smoke: geocoding → Yandex truck route → cost/profit recalculation."""
    from app.services.matching.profit_calculator import CargoProfitCalculator

    vehicle = VehicleProfile.create(
        name="12t demo truck",
        vehicle_type=VehicleType.TRUCK,
        body_type=BodyType.TENT,
        cargo_capacity_kg=12_000,
        length_cm=820,
        width_cm=250,
        height_cm=380,
        volume_m3=78.0,
        pallet_capacity=18,
        max_weight_kg=18_000,
        empty_weight_kg=6_000,
    )
    cargo = Cargo(
        id="demo-route-001",
        source_id="demo",
        title="Москва → Казань",
        loading_region="Москва",
        unloading_region="Казань",
        payment_amount=Decimal("120000"),
        distance_km=726.0,
    )
    route_request = RouteRequest(
        origin=cargo.loading_region,
        destination=cargo.unloading_region,
        vehicle=RouteVehicleParameters.from_profile(vehicle),
        traffic_enabled=True,
        alternatives=1,
    )
    estimate = await container.route_service.estimate(
        cargo.loading_region,
        cargo.unloading_region,
        trace_id="demo-routes",
        request=route_request,
    )
    if estimate is None:
        logger.error("Yandex truck route: mocked failure")
        return
    analysis = CargoProfitCalculator().analyze(cargo, estimate)
    if analysis is None:
        logger.error("Net profit recalculation failed")
        print("Net profit recalculation failed")
        return
    tolls = "yes" if estimate.has_tolls else "no"
    lines = (
        "Yandex truck route: mocked success",
        f"Distance: {estimate.distance_km:.0f} km",
        f"Duration: {estimate.duration_hours * 60:.0f} min",
        f"Tolls: {tolls}",
        f"Net profit recalculated: {analysis.net_profit} ₽",
    )
    for line in lines:
        logger.info(line)
        print(line)


def _build_telegram_bot(
    *,
    settings_service: SettingsService,
    command_bus: CommandBus,
    pipeline: RecommendationPipeline,
    collector: AnalyticsCollector,
    source_registry: SourceRegistry,
    source_runtime: SourceRuntime,
    source_configurations: object,
    matching_repository: SqliteMatchingRepository,
    cargo_repository: SqliteCargoRepository,
    scheduler: SchedulerRuntime,
    dashboard: DashboardViewModel,
    driver: DriverProfile,
    build_version: str,
) -> TelegramBotService:
    """Production-бот: данные из сервисов + тексты из bot_replies.

    Мутации идут через CommandBus (/search → RunJobNow); чтение —
    query-методы сервисов (ADR-0005: чтение не оборачивается в команды).
    """
    from decimal import Decimal

    from app.infrastructure.telegram import bot_replies

    router = TelegramCommandRouter()

    async def _start(_: str) -> str:
        return bot_replies.build_start_reply(router.commands())

    async def _help(_: str) -> str:
        return bot_replies.build_help_reply(router.commands())

    async def _status(_: str) -> str:
        report = pipeline.last_report
        health = source_runtime.health("ati")
        return bot_replies.build_status_reply(
            source_name=source_registry.get("ati").spec.name,
            health=health,
            found_count=collector.total_cargo_received(),
            last_search_at=health.last_success,
            best_route=report.best_route if report is not None else "",
            best_score=report.best_score if report is not None else 0,
            scheduler_running=scheduler.is_running,
            version=build_version,
        )

    async def _report(_: str) -> str:
        statistics = await matching_repository.get_statistics()
        history = await matching_repository.get_history(limit=10_000)
        income = sum(
            (d.profit for d in history if d.selected and d.profit is not None),
            start=Decimal(0),
        )
        return bot_replies.build_report_reply(
            found_count=collector.total_cargo_received(),
            statistics=statistics,
            income=income,
            source_errors=dict(collector.source_failures),
        )

    async def _settings(_: str) -> str:
        current = settings_service.current
        get_all = getattr(source_configurations, "get_all", None)
        configurations = get_all() if callable(get_all) else ()
        enabled = [c.name for c in configurations if c.enabled]
        return bot_replies.build_settings_reply(
            vehicle=current.vehicle.active_profile(),
            home_region=driver.home_region,
            minimum_price_per_km=driver.minimum_price_per_km,
            weights=current.matching,
            enabled_sources=enabled,
            channels=list(current.notifications.enabled_channels),
        )

    async def _search(_: str) -> str:
        # Мутация — строго через CommandBus (существующая команда RunJobNow).
        try:
            job_result = await command_bus.dispatch(RunJobNow(job_name="source:ati"))
        except Exception as exc:
            return bot_replies.build_search_failed_reply(str(exc))
        await pipeline.wait_idle()
        if job_result is not None and not job_result.success:
            return bot_replies.build_search_failed_reply(job_result.error or "источник не ответил")
        report = pipeline.last_report
        if report is None:
            health = source_runtime.health("ati")
            if health.status.value == "authenticated_no_market_access":
                return bot_replies.build_no_market_access_reply(
                    available_boards=0,
                    received=health.last_received_count,
                )
            return bot_replies.build_search_failed_reply("источник не вернул данных")
        health = source_runtime.health("ati")
        if report.received == 0 and health.status.value == "authenticated_no_market_access":
            return bot_replies.build_no_market_access_reply(available_boards=0, received=0)
        return bot_replies.build_search_result_reply(
            received=report.received,
            new_count=report.new_count + report.updated_count,
            duplicates=report.duplicates,
            best_route=report.best_route,
            best_score=report.best_score,
        )

    router.register("/start", _start, description="что умеет LogistAI")
    router.register("/help", _help, description="список команд")
    router.register("/status", _status, description="состояние ATI и платформы")
    router.register("/search", _search, description="запустить поиск грузов сейчас")
    router.register("/report", _report, description="дневная сводка аналитики")
    router.register("/settings", _settings, description="текущие настройки (read-only)")
    router.set_fallback(lambda: bot_replies.build_unknown_command_reply(router.commands()))

    async def _details(cargo_id: str) -> str | None:
        cargo = await cargo_repository.get(cargo_id)
        return bot_replies.build_cargo_details(cargo) if cargo is not None else None

    def _ignore(cargo_id: str) -> None:
        async def _ignore_and_refresh() -> None:
            await command_bus.dispatch(IgnoreCargo(cargo_id=cargo_id, actor="telegram"))
            remaining = tuple(c for c in dashboard.best_matches if c.cargo_id != cargo_id)
            dashboard.set_recommendation_cards(remaining)

        try:
            asyncio.get_running_loop().create_task(_ignore_and_refresh())
        except RuntimeError:
            asyncio.run(_ignore_and_refresh())

    return TelegramBotService(
        api_factory=TelegramClient,
        token_provider=settings_service.get_bot_token,
        chat_id_provider=settings_service.get_chat_id,
        router=router,
        details_provider=_details,
        ignore_sink=_ignore,
    )


def run_app(argv: list[str] | None = None) -> int:
    """Запустить приложение LogistAI (петля qasync). Возвращает код выхода."""
    raw_args = argv if argv is not None else sys.argv
    if "--demo-routes-smoke" in raw_args:
        container = build_container(demo_routes=True)
        try:
            asyncio.run(_run_routes_smoke(container))
        finally:
            container.database.close()
        return 0

    # Локальный импорт: Qt не должен подтягиваться при импорте модуля,
    # чтобы ядро и тесты без GUI-окружения работали свободно.
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QApplication
    from qasync import QEventLoop

    from app.ui.main_window import MainWindow
    from app.ui.menu_bar import MenuBarController
    from app.ui.theme.fonts import resolve_font_stack
    from app.ui.theme.manager import ThemeManager
    from app.ui.viewmodels import MOCK_POTENTIAL_PROFIT, mock_best_matches
    from app.ui.viewmodels.main_viewmodel import MainViewModel
    from app.ui.widgets import Command

    demo = "--demo" in raw_args or os.environ.get("LOGISTAI_DEMO") == "1"
    demo_ati = "--demo-ati" in raw_args or os.environ.get("LOGISTAI_DEMO_ATI") == "1"
    demo_routes = "--demo-routes" in raw_args or os.environ.get("LOGISTAI_DEMO_ROUTES") == "1"
    app = QApplication(
        [arg for arg in raw_args if arg not in ("--demo", "--demo-ati", "--demo-routes")]
    )
    app.setApplicationName(APP_NAME)
    app.setOrganizationDomain(ORGANIZATION_DOMAIN)
    app.setQuitOnLastWindowClosed(False)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    container = build_container(
        demo_dashboard=demo and not demo_ati,
        demo_ati=demo_ati,
        demo_routes=demo_routes,
    )
    # Тема применяется из настроек ДО сборки окна; font stack строится только
    # из реально доступных Qt families, чтобы не было SF Pro alias warning.
    from app.ui.theme import tokens as ui_tokens

    ui_tokens.FONT_STACK = resolve_font_stack()
    ui_tokens.apply_theme(container.settings_service.current.ui.theme.value)
    dashboard = container.dashboard_viewmodel
    logger.info(
        "LogistAI %s запускается%s",
        container.build_info.display(),
        (
            " (демо маршрутов)"
            if demo_routes
            else " (демо-режим)"
            if demo
            else (" (демо ATI)" if demo_ati else "")
        ),
    )

    def _show_demo_cargo() -> None:
        dashboard.set_recommendation_cards(
            mock_best_matches(), potential_profit=MOCK_POTENTIAL_PROFIT
        )

    extra_commands = (
        (
            Command(
                id="demo-cargo",
                title="Показать демо-грузы",
                subtitle="Демо-режим: три карточки рекомендаций",
                run=_show_demo_cargo,
                keywords=("demo", "демо"),
            ),
        )
        if demo
        else ()
    )
    window = MainWindow(
        MainViewModel(container.build_info, mode_label="DEMO" if demo or demo_ati else "LIVE"),
        dashboard,
        container.event_bus,
        command_dispatcher=container.command_bus,
        current_settings=container.settings_service.current,
        background_on_close=True,
        demo=demo,
        extra_commands=extra_commands,
    )
    theme_manager = ThemeManager(app, window)
    theme_manager.apply(container.settings_service.current.ui.theme, animated=False)
    window.set_theme_manager(theme_manager)
    shutdown = ShutdownCoordinator(
        event_bus=container.event_bus,
        command_bus=container.command_bus,
        telegram_bot=container.telegram_bot,
        recommendation_pipeline=container.recommendation_pipeline,
        ati_client=container.ati_client,
        database=container.database,
    )
    menu_bar = MenuBarController(
        window=window,
        events=container.event_bus,
        commands=container.command_bus,
        quit_requested=lambda: shutdown.request("menu_bar"),
        parent=app,
    )
    shutdown.set_menu_bar(menu_bar)
    menu_bar.attach()
    quit_action = QAction(window)
    quit_action.setShortcut(QKeySequence.StandardKey.Quit)
    quit_action.triggered.connect(lambda: shutdown.request("cmd_q"))
    window.addAction(quit_action)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda _signum, _frame: shutdown.request("signal"))
    window.show()
    container.event_bus.publish(AppStarted())

    async def _startup() -> None:
        await dashboard.refresh()
        autostart = MacOSLaunchAgentAutostart()
        if container.settings_service.current.ui.autostart and not autostart.is_enabled():
            autostart.enable()
        # Scheduler стартует вместе с приложением: ATI-POLL (интервал из
        # конфигурации источника) и минутный монитор здоровья работают сами.
        await container.command_bus.dispatch(StartScheduler())
        # Telegram-бот: молчит, если токен не настроен (лог, не ошибка).
        await container.telegram_bot.start()
        if demo_routes:
            await _run_routes_smoke(container)
        if demo_ati:
            await _run_ati_smoke()
        elif demo:
            # «Живой AI»: лучший груз появляется через мгновение после старта.
            await asyncio.sleep(1.2)
            _show_demo_cargo()

    async def _run_ati_smoke() -> None:
        """Немедленный опрос ATI + чек-лист готовности в лог."""
        report = await container.source_runtime.run_source("ati")
        if not report.success:
            logger.error("ATI: опрос не удался — %s", report.error)
            return
        await container.recommendation_pipeline.wait_idle()
        health = container.source_runtime.health("ati")
        logger.info("ATI подключен 🟢 (статус: %s)", health.status.value)
        pipeline_report = container.recommendation_pipeline.last_report
        received = len(report.items)
        if pipeline_report is not None:
            logger.info(
                "Получено грузов: %d (новых: %d, дубликатов: %d)",
                received,
                pipeline_report.new_count,
                pipeline_report.duplicates,
            )
            if pipeline_report.best_cargo_id:
                logger.info(
                    "Лучший груз найден: %s · AI Score рассчитан: %d",
                    pipeline_report.best_route,
                    pipeline_report.best_score,
                )
                logger.info("Уведомление отправлено через Notification Center")
        await dashboard.refresh()

    with loop:
        startup_task = loop.create_task(_startup())
        shutdown.add_startup_task(startup_task)
        startup_task.add_done_callback(
            lambda task: (
                shutdown.request("startup_failed")
                if not task.cancelled() and task.exception() is not None
                else None
            )
        )
        loop.run_until_complete(shutdown.finished.wait())
    app.quit()
    return 0
