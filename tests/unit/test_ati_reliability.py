"""Тесты Stage 9.6: дедуп с обновлениями, cooldown, восстановление, метрики."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.buses import EventBus
from app.core.events import CargoReceived, CargoUpdated
from app.core.models.history import HistoryEntry
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.notification import Notification
from app.core.models.settings import AppSettings
from app.core.models.sources import SourceStatus
from app.infrastructure.routes import MockRouteProvider
from app.infrastructure.sources.ati import AtiSource
from app.infrastructure.sources.ati.demo import (
    DemoAtiConfigurationRepository,
    DemoAtiCredentialProvider,
    build_demo_ati_client,
)
from app.infrastructure.storage.in_memory_cargo import InMemoryCargoRepository
from app.services.logistics.compatibility_service import CargoCompatibilityService
from app.services.matching import (
    CargoProfitCalculator,
    IntelligentMatchingService,
    PreferenceEngine,
    RouteScoreCalculator,
)
from app.services.notifications import NotificationCooldownPolicy
from app.services.routes import RouteCostCalculator, RouteService
from app.services.search import (
    CargoMatchingService,
    CargoPreFilter,
    CargoRankingService,
    CargoScoreCalculator,
    CargoSearchEngine,
    RecommendationPipeline,
)
from app.services.sources import (
    CargoDeduplicationService,
    CargoNormalizer,
    DeduplicationStatus,
    SourceRegistry,
    SourceRuntime,
)
from app.ui.viewmodels import MOCK_NOW, SourceStatusViewModel, mock_vehicle


def _cargo(**overrides: Any) -> Cargo:
    params: dict[str, Any] = {
        "id": "ati-1",
        "source_id": "ati",
        "weight_kg": 5000,
        "loading_region": "Москва",
        "unloading_region": "Санкт-Петербург",
        "payment_amount": Decimal(120000),
        "distance_km": 700.0,
    }
    params.update(overrides)
    return Cargo(**params)


# ── CargoDeduplicationService ────────────────────────────────────────────────


def test_same_cargo_is_duplicate() -> None:
    service = CargoDeduplicationService()
    assert service.assess(_cargo()).status is DeduplicationStatus.NEW
    assert service.assess(_cargo()).status is DeduplicationStatus.DUPLICATE


def test_price_change_is_update_with_changes() -> None:
    service = CargoDeduplicationService()
    service.assess(_cargo())
    verdict = service.assess(_cargo(payment_amount=Decimal(130000)))
    assert verdict.status is DeduplicationStatus.UPDATED
    assert verdict.changes == ("price",)


def test_route_and_weight_changes_detected() -> None:
    service = CargoDeduplicationService()
    service.assess(_cargo())
    verdict = service.assess(_cargo(unloading_region="Казань", weight_kg=5500))
    assert verdict.status is DeduplicationStatus.UPDATED
    assert set(verdict.changes) == {"route", "weight"}


def test_different_external_id_is_new() -> None:
    service = CargoDeduplicationService()
    service.assess(_cargo())
    assert service.assess(_cargo(id="ati-2")).status is DeduplicationStatus.NEW


def test_dedup_service_lru_bound() -> None:
    service = CargoDeduplicationService(capacity=2)
    for index in range(3):
        service.assess(_cargo(id=f"c-{index}"))
    assert len(service) == 2
    # самый старый вытеснен — придёт снова как новый
    assert service.assess(_cargo(id="c-0")).status is DeduplicationStatus.NEW


# ── Пайплайн: CargoUpdated и повторный подбор ────────────────────────────────


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


def _pipeline(bus: EventBus, sender: _Sender) -> RecommendationPipeline:
    repository = InMemoryCargoRepository()
    matching = CargoMatchingService(
        engine=CargoSearchEngine(
            prefilter=CargoPreFilter(),
            compatibility=CargoCompatibilityService(BasicCompatibilityChecker()),
            scorer=CargoScoreCalculator(),
            ranking=CargoRankingService(),
        ),
        repository=repository,
        event_bus=bus,
        notifications=sender,
    )
    intelligent = IntelligentMatchingService(
        preferences=PreferenceEngine(),
        profit=CargoProfitCalculator(),
        routes=RouteService(
            provider=MockRouteProvider(), costs=RouteCostCalculator(), event_bus=bus
        ),
        route_score=RouteScoreCalculator(),
        event_bus=bus,
        notifications=sender,
    )
    vehicle = mock_vehicle()
    return RecommendationPipeline(
        repository=repository,
        matching=matching,
        intelligent=intelligent,
        deduplicator=CargoDeduplicationService(),
        vehicle_provider=lambda: vehicle,
        driver_provider=lambda: DriverProfile.create(home_region="Москва"),
        location_provider=lambda: "Москва",
        event_publisher=bus,
    )


async def test_price_update_publishes_cargo_updated_and_rematches() -> None:
    bus = EventBus()
    sender = _Sender()
    updates: list[CargoUpdated] = []
    bus.subscribe(CargoUpdated, updates.append)
    pipeline = _pipeline(bus, sender)

    first = await pipeline.process(
        CargoReceived(source_id="ati", trace_id="t-1", items=(_cargo(),))
    )
    assert first.new_count == 1 and first.updated_count == 0

    # тот же груз, но дороже: событие CargoUpdated + новый подбор
    second = await pipeline.process(
        CargoReceived(
            source_id="ati", trace_id="t-2", items=(_cargo(payment_amount=Decimal(140000)),)
        )
    )
    assert second.new_count == 0 and second.updated_count == 1 and second.duplicates == 0
    assert second.best_cargo_id == "ati-1"  # обновлённый груз снова прошёл подбор
    assert len(updates) == 1
    assert updates[0].changes == ("price",)
    assert updates[0].trace_id == "t-2"

    # без изменений — чистый дубликат, подбор не запускается заново
    third = await pipeline.process(
        CargoReceived(
            source_id="ati", trace_id="t-3", items=(_cargo(payment_amount=Decimal(140000)),)
        )
    )
    assert third.duplicates == 1 and third.updated_count == 0 and third.new_count == 0


# ── NotificationCooldownPolicy ───────────────────────────────────────────────


def test_cooldown_suppresses_within_window() -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
    policy = NotificationCooldownPolicy(180.0, clock=lambda: now)
    assert policy.should_send("ati") is True  # 10:00 — уведомляем
    now = now + timedelta(minutes=1)
    assert policy.should_send("ati") is False  # 10:01 — подавлено
    now = now + timedelta(minutes=1)
    assert policy.should_send("ati") is False  # 10:02 — подавлено
    now = now + timedelta(minutes=2)
    assert policy.should_send("ati") is True  # окно 3 мин истекло


def test_cooldown_reset_allows_immediate_send() -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
    policy = NotificationCooldownPolicy(180.0, clock=lambda: now)
    policy.should_send("ati")
    assert policy.suppressed("ati")
    policy.reset("ati")  # источник восстановился
    assert policy.should_send("ati") is True  # следующая авария — сразу


# ── Runtime: спам гасится, восстановление уведомляет, метрики считаются ──────


class _History:
    async def add(self, entry: HistoryEntry) -> None:
        return None


class _FlakySource:
    """Источник, которым управляет тест: падает или отдаёт грузы."""

    def __init__(self) -> None:
        base = AtiSource(DemoAtiCredentialProvider()).spec
        self._spec = replace(
            base,
            enabled=True,
            retry_policy=replace(base.retry_policy, max_attempts=1, delay_seconds=0.0),
        )
        self.fail = True

    @property
    def spec(self) -> Any:
        return self._spec

    async def fetch(self, context: Any) -> Any:
        from app.core.errors import SourceUnavailableError
        from app.core.models.sources import SourceResult

        if self.fail:
            raise SourceUnavailableError("ATI HTTP 503")
        return SourceResult(source_id=self._spec.id, received_at=context.clock(), raw_items=())


def _flaky_runtime(
    sender: _Sender, clock_holder: dict[str, datetime]
) -> tuple[SourceRuntime, _FlakySource]:
    source = _FlakySource()
    registry = SourceRegistry(EventBus())
    registry.register(source)
    runtime = SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=EventBus(),
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        clock=lambda: clock_holder["now"],
        failure_cooldown=NotificationCooldownPolicy(180.0, clock=lambda: clock_holder["now"]),
        duplicates_provider=lambda source_id: 0,
    )
    return runtime, source


async def test_failure_spam_collapsed_and_recovery_notifies() -> None:
    sender = _Sender()
    clock = {"now": datetime(2026, 7, 31, 10, 0, tzinfo=UTC)}
    runtime, source = _flaky_runtime(sender, clock)

    await runtime.run_source("ati")  # 10:00 — уведомление
    clock["now"] += timedelta(minutes=1)
    await runtime.run_source("ati")  # 10:01 — подавлено
    clock["now"] += timedelta(minutes=1)
    await runtime.run_source("ati")  # 10:02 — подавлено

    failure_titles = [n.title for n in sender.sent if "не удалось" in n.title]
    assert len(failure_titles) == 1  # одно сообщение вместо трёх

    source.fail = False
    clock["now"] += timedelta(minutes=1)
    await runtime.run_source("ati")  # восстановление

    recovered = [n for n in sender.sent if "восстановлен" in n.title]
    assert len(recovered) == 1 and "🟢" in recovered[0].title

    # cooldown сброшен: новая авария уведомляет немедленно
    source.fail = True
    clock["now"] += timedelta(seconds=30)
    await runtime.run_source("ati")
    failure_titles = [n.title for n in sender.sent if "не удалось" in n.title]
    assert len(failure_titles) == 2


async def test_health_production_metrics() -> None:
    sender = _Sender()
    clock = {"now": datetime(2026, 7, 31, 10, 0, tzinfo=UTC)}
    client, _ = build_demo_ati_client()
    registry = SourceRegistry(EventBus())
    registry.register(AtiSource(DemoAtiCredentialProvider(), client=client))
    duplicates = {"ati": 0}
    runtime = SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=EventBus(),
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        configurations=DemoAtiConfigurationRepository(),
        clock=lambda: clock["now"],
        duplicates_provider=lambda source_id: duplicates[source_id],
    )

    await runtime.run_source("ati")
    clock["now"] += timedelta(hours=1)
    duplicates["ati"] = 1
    await runtime.run_source("ati")

    health = runtime.health("ati")
    assert health.status is SourceStatus.ONLINE
    assert health.error_rate == 0.0
    assert health.items_received == 10  # 5 + 5 (дедуп — забота пайплайна)
    assert health.duplicate_rate == 0.1  # 1 дубль из 10 по данным пайплайна
    assert 9.0 < health.cargos_per_hour <= 10.0  # 10 грузов за час
    assert health.last_success_duration_ms >= 0
    assert health.average_duration_ms >= 0  # avg_response_time

    view = SourceStatusViewModel.from_health("ati", "ATI.SU", health, cargo_count=10, now=MOCK_NOW)
    assert "грузов/ч" in view.throughput
    assert "дубли 10%" in view.reliability
