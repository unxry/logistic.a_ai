"""Тесты Route Intelligence (Stage 8.5): провайдер, стоимость, экономика,
интеграция с подбором, события, маршрутная аналитика, настройки."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.buses import EventBus
from app.core.clock import utc_now
from app.core.events import ProfitCalculated, RouteCalculated
from app.core.models.analytics import RouteAnalytics, summarize_routes
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.matching import MatchingContext, MatchingDecision, MatchingWeights
from app.core.models.routes import (
    PROVIDER_CONFIDENCE,
    SYNTHETIC_CONFIDENCE,
    Route,
    RouteCostPolicy,
    RouteEstimate,
)
from app.core.models.search import CargoSearchQuery
from app.core.models.settings import AppSettings
from app.infrastructure.routes import MockRouteProvider
from app.infrastructure.settings.migrations import MIGRATIONS, apply_migrations
from app.infrastructure.settings.serialization import settings_from_dict, settings_to_dict
from app.infrastructure.storage.database import Database
from app.infrastructure.storage.matching_repository import SqliteMatchingRepository
from app.services.logistics.compatibility_service import CargoCompatibilityService
from app.services.matching import (
    CargoProfitCalculator,
    IntelligentMatchingService,
    PreferenceEngine,
    RouteScoreCalculator,
)
from app.services.monitoring import AnalyticsCollector, MatchingQualityService
from app.services.routes import RouteCostCalculator, RouteService
from app.services.search import (
    CargoPreFilter,
    CargoRankingService,
    CargoScoreCalculator,
    CargoSearchEngine,
)

MAN_TGL = VehicleProfile.create(
    name="MAN TGL",
    vehicle_type=VehicleType.TRUCK,
    body_type=BodyType.TENT,
    cargo_capacity_kg=6000,
    length_cm=620,
    width_cm=245,
    height_cm=250,
    volume_m3=38.0,
    pallet_capacity=14,
)


def _cargo(**overrides: Any) -> Cargo:
    params: dict[str, Any] = {
        "id": uuid4().hex,
        "source_id": "test",
        "weight_kg": 5000,
        "volume_m3": 25.0,
        "loading_region": "Москва",
        "unloading_region": "Санкт-Петербург",
        "payment_amount": Decimal(120000),
        "distance_km": 700.0,
    }
    params.update(overrides)
    return Cargo(**params)


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, notification: Any) -> None:
        self.sent.append(notification)


class Rig:
    """Полный стек подбора с MockRouteProvider и перехватом событий маршрутов."""

    def __init__(
        self,
        driver: DriverProfile,
        *,
        provider: MockRouteProvider | None = None,
        weights: MatchingWeights | None = None,
        route_estimate: RouteEstimate | None = None,
    ) -> None:
        self.bus = EventBus()
        self.sender = _Sender()
        self.route_events: list[RouteCalculated] = []
        self.profit_events: list[ProfitCalculated] = []
        self.bus.subscribe(RouteCalculated, self.route_events.append)
        self.bus.subscribe(ProfitCalculated, self.profit_events.append)
        self.provider = provider if provider is not None else MockRouteProvider()
        self.service = IntelligentMatchingService(
            preferences=PreferenceEngine(),
            profit=CargoProfitCalculator(),
            routes=RouteService(
                provider=self.provider, costs=RouteCostCalculator(), event_bus=self.bus
            ),
            route_score=RouteScoreCalculator(),
            event_bus=self.bus,
            notifications=self.sender,
            weights=weights,
        )
        self.context = MatchingContext(
            vehicle_profile=MAN_TGL,
            driver_profile=driver,
            current_location="Москва",
            route_estimate=route_estimate,
        )

    def matches(self, *cargos: Cargo) -> tuple[Any, ...]:
        engine = CargoSearchEngine(
            prefilter=CargoPreFilter(),
            compatibility=CargoCompatibilityService(BasicCompatibilityChecker()),
            scorer=CargoScoreCalculator(),
            ranking=CargoRankingService(),
        )
        query = CargoSearchQuery.create(MAN_TGL.id)
        return tuple(engine.match_single(c, MAN_TGL, query) for c in cargos)


# ── MockRouteProvider: расчёт расстояния ─────────────────────────────────────


async def test_provider_returns_known_route() -> None:
    estimate = await MockRouteProvider().calculate_route("Москва", "Санкт-Петербург")
    assert estimate is not None
    assert estimate.distance_km == 710.0
    assert estimate.duration_hours == 10.0
    assert estimate.confidence_score == PROVIDER_CONFIDENCE


async def test_provider_lookup_is_symmetric() -> None:
    estimate = await MockRouteProvider().calculate_route("Санкт-Петербург", "Москва")
    assert estimate is not None and estimate.distance_km == 710.0


async def test_provider_same_location_is_zero() -> None:
    estimate = await MockRouteProvider().calculate_route("Москва", "Москва")
    assert estimate is not None
    assert estimate.distance_km == 0.0 and estimate.confidence_score == 100


async def test_provider_unknown_route_returns_none() -> None:
    assert await MockRouteProvider().calculate_route("Пермь", "Сургут") is None


# ── RouteCostCalculator: топливо и стоимость рейса ───────────────────────────


def test_fuel_cost_exact() -> None:
    """710 км × 30 л/100 км × 70 ₽/л = 14 910 ₽ (Decimal, без потерь)."""
    assert RouteCostCalculator().fuel_cost(710.0) == Decimal(14910)


def test_fuel_formula_matches_spec_form() -> None:
    """Форма ТЗ distance / расход(км/л) × цена эквивалентна реализации."""
    policy = RouteCostPolicy()
    spec_form = Decimal("710") / policy.fuel_consumption_km_per_liter * policy.fuel_price_per_liter
    implemented = RouteCostCalculator(policy).fuel_cost(710.0)
    assert spec_form.quantize(Decimal("0.01")) == implemented.quantize(Decimal("0.01"))


def test_trip_cost_spec_example() -> None:
    """Эталон ТЗ: 710 км / 10 ч → 14 910 + 6 390 + 7 100 + 6 600 = 35 000 ₽."""
    calc = RouteCostCalculator()
    assert calc.toll_cost(710.0) == Decimal(6390)
    assert calc.maintenance_cost(710.0) == Decimal(7100)
    assert calc.driver_cost(10.0) == Decimal(6600)
    assert calc.trip_cost(710.0, 10.0) == Decimal(35000)


def test_enrich_fills_costs_and_keeps_provider_tolls() -> None:
    calc = RouteCostCalculator()
    enriched = calc.enrich(RouteEstimate(distance_km=710.0, duration_hours=10.0))
    assert enriched.total_cost == Decimal(35000)
    assert enriched.fuel_cost == Decimal(14910)
    # провайдер знает платные участки точнее усреднённого тарифа
    with_tolls = calc.enrich(
        RouteEstimate(distance_km=710.0, duration_hours=10.0, toll_cost=Decimal(4000))
    )
    assert with_tolls.toll_cost == Decimal(4000)
    assert with_tolls.total_cost == Decimal(35000) - Decimal(6390) + Decimal(4000)


def test_empty_run_cost_is_fuel_plus_wear() -> None:
    """Холостой подгон: 170 км × (21 + 10) ₽/км = 5 270 ₽."""
    assert RouteCostCalculator().empty_run_cost(170.0) == Decimal(5270)


def test_synthetic_estimate_uses_average_speed() -> None:
    estimate = RouteCostCalculator().synthetic_estimate(710.0)
    assert estimate.confidence_score == SYNTHETIC_CONFIDENCE
    assert estimate.duration_hours == pytest.approx(10.0)  # 710 / 71 км/ч
    assert estimate.total_cost == Decimal(35000)


def test_policy_validation() -> None:
    with pytest.raises(ValueError, match="отрицательн"):
        RouteCostPolicy(fuel_price_per_liter=Decimal(-1))
    with pytest.raises(ValueError, match="скорость"):
        RouteCostPolicy(average_speed_kmh=0.0)


# ── RouteService: события, кэш, синтетика ────────────────────────────────────


def _route_service(bus: EventBus, provider: MockRouteProvider) -> RouteService:
    return RouteService(provider=provider, costs=RouteCostCalculator(), event_bus=bus)


async def test_route_service_publishes_route_calculated() -> None:
    bus = EventBus()
    events: list[RouteCalculated] = []
    bus.subscribe(RouteCalculated, events.append)
    service = _route_service(bus, MockRouteProvider())

    estimate = await service.estimate("Москва", "Санкт-Петербург", trace_id="t-route")

    assert estimate is not None and estimate.total_cost == Decimal(35000)
    assert len(events) == 1
    route = events[0].route
    assert isinstance(route, Route)
    assert route.from_location == "Москва" and route.to_location == "Санкт-Петербург"
    assert route.distance_km == 710.0 and route.estimated_hours == 10.0
    assert route.fuel_cost == Decimal(14910) and route.toll_cost == Decimal(6390)
    assert events[0].trace_id == "t-route"


async def test_route_service_caches_estimates() -> None:
    bus = EventBus()
    events: list[RouteCalculated] = []
    bus.subscribe(RouteCalculated, events.append)
    provider = MockRouteProvider()
    service = _route_service(bus, provider)

    first = await service.estimate("Москва", "Казань")
    second = await service.estimate("Москва", "Казань")

    assert first == second
    assert provider.calls == 1  # второе обращение — из кэша
    assert len(events) == 1  # событие публикуется один раз


async def test_route_service_synthetic_fallback_for_cargo() -> None:
    bus = EventBus()
    events: list[RouteCalculated] = []
    bus.subscribe(RouteCalculated, events.append)
    service = _route_service(bus, MockRouteProvider(routes={}))

    cargo = _cargo(loading_region="Пермь", unloading_region="Сургут", distance_km=1000.0)
    estimate = await service.estimate_for_cargo(cargo)

    assert estimate is not None
    assert estimate.confidence_score == SYNTHETIC_CONFIDENCE
    assert estimate.distance_km == 1000.0
    assert estimate.duration_hours == pytest.approx(1000.0 / 71.0)
    assert events == []  # синтетика — не рассчитанный маршрут


async def test_route_service_none_without_any_distance() -> None:
    service = _route_service(EventBus(), MockRouteProvider(routes={}))
    cargo = _cargo(loading_region="Пермь", unloading_region="Сургут", distance_km=None)
    assert await service.estimate_for_cargo(cargo) is None


async def test_route_service_survives_provider_failure() -> None:
    class _Broken:
        async def calculate_route(self, origin: str, destination: str) -> RouteEstimate | None:
            raise RuntimeError("картографический сервис упал")

    service = RouteService(provider=_Broken(), costs=RouteCostCalculator(), event_bus=EventBus())
    assert await service.estimate("Москва", "Санкт-Петербург") is None


async def test_route_service_without_provider() -> None:
    service = RouteService(provider=None, costs=RouteCostCalculator(), event_bus=EventBus())
    assert await service.estimate("Москва", "Санкт-Петербург") is None


async def test_empty_run_cost_via_service() -> None:
    service = _route_service(EventBus(), MockRouteProvider())
    assert await service.empty_run_cost("Тверь", "Москва") == Decimal(5270)  # 170 км × 31 ₽
    assert await service.empty_run_cost("Москва", "Москва") == Decimal(0)
    assert await service.empty_run_cost("Пермь", "Сургут") == Decimal(0)  # честно не знаем


# ── Экономика: прибыль, холостой прогон, убыточный груз ──────────────────────


def test_profit_includes_empty_run() -> None:
    route = RouteCostCalculator().enrich(RouteEstimate(distance_km=710.0, duration_hours=10.0))
    analysis = CargoProfitCalculator().analyze(_cargo(), route, empty_run_cost=Decimal(5270))
    assert analysis is not None
    assert analysis.empty_run_cost == Decimal(5270)
    assert analysis.expenses == Decimal(40270)
    assert analysis.net_profit == Decimal(79730)


def test_profit_per_hour_none_without_duration() -> None:
    route = RouteCostCalculator().enrich(RouteEstimate(distance_km=100.0, duration_hours=0.0))
    analysis = CargoProfitCalculator().analyze(_cargo(), route)
    assert analysis is not None and analysis.profit_per_hour is None


async def test_unprofitable_cargo_scores_zero_profit() -> None:
    rig = Rig(DriverProfile.create(home_region="Москва"))
    ranked = await rig.service.rank(rig.matches(_cargo(payment_amount=Decimal(20000))), rig.context)
    assert len(ranked) == 1
    match = ranked[0]
    assert match.profit is not None and match.profit.net_profit == Decimal(-15000)
    assert match.profit_score == 0
    assert any("Убыточный груз" in line for line in match.explanation)


# ── Интеграция с подбором ────────────────────────────────────────────────────


async def test_matching_uses_provider_distance_over_listing() -> None:
    """Провайдер (710 км) точнее объявления (700 км) — экономика по маршруту."""
    rig = Rig(DriverProfile.create(home_region="Москва"))
    best = await rig.service.select_best(rig.matches(_cargo(distance_km=700.0)), rig.context)
    assert best is not None
    assert best.route_estimate is not None and best.route_estimate.distance_km == 710.0
    assert best.profit is not None and best.profit.expenses == Decimal(35000)


async def test_context_route_estimate_overrides_provider() -> None:
    provider = MockRouteProvider(routes={})
    preset = RouteCostCalculator().enrich(RouteEstimate(distance_km=710.0, duration_hours=10.0))
    rig = Rig(DriverProfile.create(home_region="Москва"), provider=provider, route_estimate=preset)

    best = await rig.service.select_best(rig.matches(_cargo()), rig.context)

    assert best is not None and best.route_estimate == preset
    assert provider.calls == 0  # готовая оценка из контекста — провайдер не нужен


async def test_custom_weights_change_scoring() -> None:
    profit_only = MatchingWeights(
        compatibility=0.0, profit=1.0, route=0.0, preferences=0.0, freshness=0.0
    )
    rig = Rig(DriverProfile.create(home_region="Москва"), weights=profit_only)
    ranked = await rig.service.rank(rig.matches(_cargo()), rig.context)
    assert ranked[0].final_score == ranked[0].profit_score  # вес прибыли 100%


def test_invalid_weights_rejected() -> None:
    with pytest.raises(ValueError, match="Сумма весов"):
        MatchingWeights(compatibility=0.5, profit=0.5, route=0.5, preferences=0.0, freshness=0.0)
    with pytest.raises(ValueError, match="отрицательным"):
        MatchingWeights(compatibility=1.2, profit=0.0, route=0.0, preferences=-0.2, freshness=0.0)


async def test_freshness_prefers_new_cargo() -> None:
    rig = Rig(DriverProfile.create(home_region="Москва"))
    stale = _cargo(created_at=utc_now() - timedelta(hours=12))
    fresh = _cargo()
    ranked = await rig.service.rank(rig.matches(stale, fresh), rig.context)
    assert [m.cargo_match.cargo_id for m in ranked] == [fresh.id, stale.id]
    assert ranked[0].freshness_score > ranked[1].freshness_score


async def test_empty_run_reduces_profit_in_matching() -> None:
    """Из Твери подгон в Москву (170 км) съедает 5 270 ₽ прибыли."""
    rig = Rig(DriverProfile.create())
    context = MatchingContext(
        vehicle_profile=MAN_TGL,
        driver_profile=rig.context.driver_profile,
        current_location="Тверь",
    )
    best = await rig.service.select_best(rig.matches(_cargo()), context)
    assert best is not None and best.profit is not None
    assert best.profit.empty_run_cost == Decimal(5270)
    assert best.profit.net_profit == Decimal(85000) - Decimal(5270)
    assert any("Холостой подгон" in line for line in best.explanation)


async def test_trace_id_spans_route_profit_and_decision() -> None:
    rig = Rig(DriverProfile.create(home_region="Москва"))
    best = await rig.service.select_best(rig.matches(_cargo()), rig.context, trace_id="t-85")
    assert best is not None
    assert rig.route_events and all(e.trace_id == "t-85" for e in rig.route_events)
    assert rig.profit_events and all(e.trace_id == "t-85" for e in rig.profit_events)
    assert rig.profit_events[0].analysis.net_profit == Decimal(85000)


# ── Маршрутная аналитика ─────────────────────────────────────────────────────


def _decision(**overrides: Any) -> MatchingDecision:
    params: dict[str, Any] = {
        "cargo_id": uuid4().hex,
        "driver_id": "d1",
        "score": 90,
        "selected": True,
        "profit": Decimal(85000),
        "route": "Москва → Санкт-Петербург",
        "distance_km": 710.0,
        "trace_id": "t",
    }
    params.update(overrides)
    return MatchingDecision.create(**params)


def test_summarize_routes_best_and_worst() -> None:
    decisions = [
        _decision(profit=Decimal(85000)),
        _decision(profit=Decimal(80000)),
        _decision(route="Москва → Казань", distance_km=820.0, profit=Decimal(20000)),
        _decision(selected=False, profit=None, rejected_reason="Перегруз"),
    ]
    analytics = summarize_routes(decisions)
    assert analytics.routes_count == 2
    assert analytics.best_routes[0].route == "Москва → Санкт-Петербург"
    assert analytics.best_routes[0].average_profit == Decimal(82500)
    assert analytics.best_routes[0].decision_count == 2
    assert analytics.worst_routes[0].route == "Москва → Казань"
    assert analytics.average_distance_km == pytest.approx((710 + 710 + 820) / 3)
    assert analytics.average_profit_per_km > 0


def test_summarize_routes_empty() -> None:
    assert summarize_routes(()) == RouteAnalytics()
    assert MatchingQualityService().routes(()).routes_count == 0


async def test_repository_stores_distance_and_route_statistics(tmp_path: Path) -> None:
    database = Database(tmp_path / "r.db")
    database.connect()
    repo = SqliteMatchingRepository(database)
    await repo.save_decision(_decision())
    await repo.save_decision(
        _decision(route="Москва → Казань", distance_km=820.0, profit=Decimal(20000))
    )

    loaded = await repo.get_history()
    assert {d.distance_km for d in loaded} == {710.0, 820.0}
    analytics = await repo.route_statistics()
    assert analytics.best_routes[0].route == "Москва → Санкт-Петербург"
    assert analytics.worst_routes[0].route == "Москва → Казань"


async def test_database_migrates_v2_to_v3(tmp_path: Path) -> None:
    """База Stage 8 (schema v2) получает колонку distance_km без потери данных."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE history (id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL,
            kind TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
            trace_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE matching_decisions (id TEXT PRIMARY KEY, cargo_id TEXT NOT NULL,
            vehicle_profile_id TEXT NOT NULL DEFAULT '', driver_id TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL, profit TEXT, explanation TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '', selected INTEGER NOT NULL,
            rejected_reason TEXT NOT NULL DEFAULT '', trace_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL);
        INSERT INTO matching_decisions (id, cargo_id, score, selected, created_at)
            VALUES ('old1', 'c1', 90, 1, '2026-07-30T12:00:00+00:00');
        PRAGMA user_version = 2;
        """
    )
    conn.commit()
    conn.close()

    database = Database(path)
    database.connect()
    repo = SqliteMatchingRepository(database)

    loaded = await repo.get_history()
    assert loaded[0].id == "old1" and loaded[0].distance_km is None  # старые строки живы
    await repo.save_decision(_decision())  # новые пишутся с дистанцией
    assert any(d.distance_km == 710.0 for d in await repo.get_history())


def test_collector_tracks_route_and_profit_events() -> None:
    bus = EventBus()
    collector = AnalyticsCollector()
    collector.attach(bus)
    calc = RouteCostCalculator()
    for distance in (710.0, 420.0):
        estimate = calc.enrich(RouteEstimate(distance_km=distance, duration_hours=distance / 71))
        bus.publish(RouteCalculated(route=Route.create("A", "B", estimate), trace_id="t"))
    analysis = CargoProfitCalculator().analyze(
        _cargo(), calc.enrich(RouteEstimate(distance_km=710.0, duration_hours=10.0))
    )
    assert analysis is not None
    bus.publish(ProfitCalculated(cargo_id="c1", analysis=analysis, trace_id="t"))

    assert collector.routes_calculated == 2
    assert collector.average_route_distance_km() == pytest.approx(565.0)
    assert collector.profits_calculated == 1
    assert round(collector.average_profit_per_km()) == 120


# ── Настройки: секции routing и matching ─────────────────────────────────────


def test_settings_roundtrip_routing_and_matching() -> None:
    settings = AppSettings(
        routing=RouteCostPolicy(fuel_price_per_liter=Decimal(75), toll_cost_per_km=Decimal(0)),
        matching=MatchingWeights(
            compatibility=0.4, profit=0.4, route=0.1, preferences=0.05, freshness=0.05
        ),
    )
    restored = settings_from_dict(settings_to_dict(settings))
    assert restored.routing.fuel_price_per_liter == Decimal(75)
    assert restored.routing.toll_cost_per_km == Decimal(0)
    assert restored.matching.profit == 0.4


def test_settings_tolerate_garbage_weights_and_tariffs() -> None:
    data = settings_to_dict(AppSettings())
    data["matching"] = {"compatibility": 0.9, "profit": 0.9}  # сумма ≠ 1.0
    data["routing"] = {"fuel_price_per_liter": -5, "average_speed_kmh": "быстро"}
    restored = settings_from_dict(data)
    assert restored.matching == MatchingWeights()  # дефолты вместо мусора
    assert restored.routing == RouteCostPolicy()


def test_settings_migration_v1_to_v2() -> None:
    migrated = apply_migrations({"schema_version": 1, "ui": {"theme": "dark"}}, MIGRATIONS, 2)
    assert migrated["schema_version"] == 2
    assert "routing" in migrated and "matching" in migrated
    assert migrated["ui"] == {"theme": "dark"}  # существующие секции не тронуты
