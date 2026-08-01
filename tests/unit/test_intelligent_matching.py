"""Тесты Intelligent Matching: прибыль, предпочтения, ранжирование, e2e.

Stage 8.5: подбор асинхронный, маршрут даёт RouteService (MockRouteProvider),
экономика — ProfitAnalysis, уведомление — категория ROUTE.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.buses import EventBus
from app.core.events import (
    BestCargoSelected,
    CargoRejectedByPreference,
    MatchingDecisionCreated,
)
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.matching import MatchingContext
from app.core.models.notification import Notification, NotificationCategory
from app.core.models.routes import RouteEstimate
from app.core.models.search import CargoSearchQuery
from app.infrastructure.routes import MockRouteProvider
from app.services.logistics.compatibility_service import CargoCompatibilityService
from app.services.matching import (
    CargoProfitCalculator,
    IntelligentMatchingService,
    PreferenceEngine,
    RouteScoreCalculator,
)
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
        "length_cm": 500,
        "width_cm": 200,
        "height_cm": 220,
        "loading_region": "Москва",
        "unloading_region": "Санкт-Петербург",
        "payment_amount": Decimal(120000),
        "distance_km": 700.0,
    }
    params.update(overrides)
    return Cargo(**params)


def _engine() -> CargoSearchEngine:
    return CargoSearchEngine(
        prefilter=CargoPreFilter(),
        compatibility=CargoCompatibilityService(BasicCompatibilityChecker()),
        scorer=CargoScoreCalculator(),
        ranking=CargoRankingService(),
    )


def _spb_route() -> RouteEstimate:
    """Эталон ТЗ: Москва → Санкт-Петербург, 710 км, 10 ч, расходы 35 000 ₽."""
    return RouteCostCalculator().enrich(RouteEstimate(distance_km=710.0, duration_hours=10.0))


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class Rig:
    def __init__(self, driver: DriverProfile) -> None:
        self.bus = EventBus()
        self.sender = _Sender()
        self.best_events: list[BestCargoSelected] = []
        self.pref_rejects: list[CargoRejectedByPreference] = []
        self.decisions_events: list[MatchingDecisionCreated] = []
        self.bus.subscribe(BestCargoSelected, self.best_events.append)
        self.bus.subscribe(CargoRejectedByPreference, self.pref_rejects.append)
        self.bus.subscribe(MatchingDecisionCreated, self.decisions_events.append)
        self.service = IntelligentMatchingService(
            preferences=PreferenceEngine(),
            profit=CargoProfitCalculator(),
            routes=RouteService(
                provider=MockRouteProvider(),
                costs=RouteCostCalculator(),
                event_bus=self.bus,
            ),
            route_score=RouteScoreCalculator(),
            event_bus=self.bus,
            notifications=self.sender,
        )
        self.context = MatchingContext(
            vehicle_profile=MAN_TGL, driver_profile=driver, current_location="Москва"
        )

    def matches(self, *cargos: Cargo) -> tuple[Any, ...]:
        query = CargoSearchQuery.create(MAN_TGL.id)
        return tuple(_engine().match_single(c, MAN_TGL, query) for c in cargos)


# ── Прибыль (пример из ТЗ) ───────────────────────────────────────────────────


def test_profit_spec_example() -> None:
    """120 000 ₽ дохода, маршрут 710 км/10 ч → 35 000 ₽ расходов, 85 000 ₽ чистыми."""
    analysis = CargoProfitCalculator().analyze(_cargo(), _spb_route())
    assert analysis is not None
    assert analysis.gross_profit == Decimal(120000)
    assert analysis.expenses == Decimal(35000)
    assert analysis.net_profit == Decimal(85000)
    assert analysis.profit_per_km is not None and round(analysis.profit_per_km) == 120
    assert analysis.profit_per_hour == Decimal(8500)


def test_profit_none_without_price_or_route() -> None:
    calc = CargoProfitCalculator()
    assert calc.analyze(_cargo(payment_amount=None), _spb_route()) is None
    assert calc.analyze(_cargo(), None) is None


# ── Предпочтения ─────────────────────────────────────────────────────────────


def test_preferred_region_gives_bonus_and_note() -> None:
    driver = DriverProfile.create(preferred_regions=("Санкт-Петербург",))
    rig = Rig(driver)
    verdict = PreferenceEngine().evaluate(rig.matches(_cargo())[0], driver)
    assert verdict.score > 50
    assert "Ваше направление" in verdict.notes


async def test_forbidden_region_rejects() -> None:
    driver = DriverProfile.create(forbidden_regions=("Сочи",))
    rig = Rig(driver)
    ranked = await rig.service.rank(rig.matches(_cargo(unloading_region="Сочи")), rig.context)
    assert ranked == ()
    assert len(rig.pref_rejects) == 1
    assert "Сочи" in rig.pref_rejects[0].reason
    # решение зафиксировано для будущего обучения
    assert any(not e.decision.selected for e in rig.decisions_events)


def test_low_rate_penalized() -> None:
    driver = DriverProfile.create(minimum_price_per_km=Decimal(200))
    verdict = PreferenceEngine().evaluate(Rig(driver).matches(_cargo())[0], driver)
    assert verdict.score < 50  # 120000/700 ≈ 171 < 200


# ── Главный сценарий ТЗ: выбор лучшего с объяснением ─────────────────────────


async def test_main_scenario_best_choice_with_explanation() -> None:
    driver = DriverProfile.create(preferred_regions=("Санкт-Петербург",), home_region="Москва")
    rig = Rig(driver)
    cargo_spb = _cargo(payment_amount=Decimal(120000), distance_km=700.0)
    cargo_kazan = _cargo(
        unloading_region="Казань", payment_amount=Decimal(90000), distance_km=800.0
    )

    best = await rig.service.select_best(rig.matches(cargo_spb, cargo_kazan), rig.context)

    assert best is not None
    assert best.cargo_match.cargo_id == cargo_spb.id  # прибыль + направление решают
    assert best.final_score >= 70
    assert best.profit is not None and best.profit.net_profit == Decimal(85000)
    assert best.route_estimate is not None and best.route_estimate.distance_km == 710.0
    # объяснение содержит причины
    text = " ".join(best.explanation)
    assert "совместимость" in text.lower()
    assert "Прибыль 85000 ₽" in text
    assert "Ваше направление" in text
    assert "холостой пробег" in text
    # события и решения
    assert len(rig.best_events) == 1
    assert rig.best_events[0].cargo_id == cargo_spb.id
    assert any(e.decision.selected for e in rig.decisions_events)
    assert rig.best_events[0].trace_id == rig.decisions_events[-1].decision.trace_id
    # решение хранит фактическую дистанцию маршрута (для аналитики ₽/км)
    selected = [e.decision for e in rig.decisions_events if e.decision.selected]
    assert selected[0].distance_km == 710.0


async def test_ranking_ten_cargos_best_first() -> None:
    driver = DriverProfile.create(home_region="Москва")
    rig = Rig(driver)
    cargos = [
        _cargo(payment_amount=Decimal(40000 + i * 10000), distance_km=700.0) for i in range(10)
    ]
    ranked = await rig.service.rank(rig.matches(*cargos), rig.context)

    assert len(ranked) == 10
    scores = [m.final_score for m in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].profit is not None
    assert ranked[0].profit.gross_profit == Decimal(130000)  # самый дорогой — первый


# ── E2E: поиск → интеллектуальный выбор → уведомление ────────────────────────


async def test_e2e_notification_with_reasons() -> None:
    driver = DriverProfile.create(preferred_regions=("Санкт-Петербург",), home_region="Москва")
    rig = Rig(driver)
    best = await rig.service.select_best(rig.matches(_cargo(url="https://ati.su/c/1")), rig.context)
    assert best is not None

    await rig.service.notify_best(best, trace_id="t-e2e")

    assert len(rig.sender.sent) == 1
    notification = rig.sender.sent[0]
    assert notification.title == "🚚 Лучший груз найден"
    assert notification.category is NotificationCategory.ROUTE
    body = notification.body
    assert "Москва → Санкт-Петербург" in body
    assert "Расстояние: 710 км" in body
    assert "Доход: 120 000 ₽" in body
    assert "Расходы: 35 000 ₽" in body
    assert "Чистая прибыль: 85 000 ₽" in body
    assert "Прибыль: 120 ₽/км" in body
    assert "Совместимость: 100%" in body
    assert "✅" in body
    assert notification.trace_id == "t-e2e"
    assert notification.actions[0].url == "https://ati.su/c/1"
