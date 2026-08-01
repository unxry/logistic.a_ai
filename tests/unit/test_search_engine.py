"""Тесты Search Engine: сценарий ТЗ, префильтр, скоринг, ранжирование, e2e."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.buses import EventBus
from app.core.clock import utc_now
from app.core.events import CargoMatched, CargoRejected, SearchCompleted
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.notification import Notification
from app.core.models.search import CargoSearchQuery
from app.core.models.sources import RawCargo
from app.infrastructure.storage.in_memory_cargo import InMemoryCargoRepository
from app.services.logistics.compatibility_service import CargoCompatibilityService
from app.services.search import (
    CargoMatchingService,
    CargoPreFilter,
    CargoRankingService,
    CargoScoreCalculator,
    CargoSearchEngine,
)
from app.services.sources import CargoNormalizer

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


def _query(**criteria: Any) -> CargoSearchQuery:
    return CargoSearchQuery.create(MAN_TGL.id, **criteria)


# ── Главный сценарий ТЗ ──────────────────────────────────────────────────────


def test_main_scenario_from_spec() -> None:
    """Груз А (5000 кг) подходит с высокой оценкой; Б (7000 кг) отклонён."""
    cargo_a = _cargo(weight_kg=5000)
    cargo_b = _cargo(weight_kg=7000, volume_m3=20.0)

    result = _engine().search(_query(), MAN_TGL, [cargo_a, cargo_b])

    assert result.total_candidates == 2
    match_a = next(m for m in result.matches if m.cargo_id == cargo_a.id)
    match_b = next(m for m in result.matches if m.cargo_id == cargo_b.id)

    assert match_a.compatible and match_a.score >= 70
    assert not match_b.compatible and match_b.score == 0
    assert any(
        "Превышена грузоподъемность" in r for r in match_b.compatibility_result.rejection_reasons
    )
    assert result.best is match_a  # совместимый — первый


# ── PreFilter ────────────────────────────────────────────────────────────────


def test_prefilter_criteria() -> None:
    prefilter = CargoPreFilter()

    ok, _ = prefilter.passes(_cargo(), _query())
    assert ok

    ok, reason = prefilter.passes(_cargo(loading_region="Казань"), _query(regions=("Москва",)))
    assert not ok and "Регион" in reason

    ok, reason = prefilter.passes(
        _cargo(category=CargoCategory.FOOD), _query(categories=(CargoCategory.FURNITURE,))
    )
    assert not ok and "Категория" in reason

    ok, reason = prefilter.passes(_cargo(payment_amount=None), _query(min_price=Decimal(50000)))
    assert not ok and "цены" in reason

    ok, reason = prefilter.passes(_cargo(weight_kg=9000), _query(max_weight_kg=6000))
    assert not ok and "больше максимального" in reason

    ok, reason = prefilter.passes(_cargo(distance_km=3000.0), _query(max_distance_km=1000.0))
    assert not ok and "Расстояние" in reason

    # отсутствие данных префильтр не отбрасывает (решает совместимость)
    ok, _ = prefilter.passes(_cargo(weight_kg=None), _query(max_weight_kg=6000))
    assert ok


# ── Scoring ──────────────────────────────────────────────────────────────────


def test_scoring_favors_rate_and_freshness() -> None:
    engine = _engine()
    query = _query()

    rich = engine.match_single(
        _cargo(payment_amount=Decimal(150000), distance_km=500.0), MAN_TGL, query
    )
    poor = engine.match_single(
        _cargo(payment_amount=Decimal(20000), distance_km=1500.0), MAN_TGL, query
    )
    assert rich.score > poor.score

    fresh = engine.match_single(_cargo(), MAN_TGL, query)
    stale = engine.match_single(
        replace(_cargo(), created_at=utc_now() - timedelta(hours=30)), MAN_TGL, query
    )
    assert fresh.score > stale.score  # свежий заказ ценнее


def test_incompatible_score_is_zero() -> None:
    match = _engine().match_single(_cargo(weight_kg=9000), MAN_TGL, _query())
    assert match.score == 0


# ── Ranking ──────────────────────────────────────────────────────────────────


def test_ranking_order_and_positions() -> None:
    cargos = [
        _cargo(weight_kg=9000),  # несовместимый
        _cargo(payment_amount=Decimal(180000), distance_km=600.0),  # лучший
        _cargo(payment_amount=Decimal(60000), distance_km=600.0),
    ]
    result = _engine().search(_query(), MAN_TGL, cargos)

    assert [m.ranking_position for m in result.matches] == [1, 2, 3]
    assert result.matches[0].compatible and result.matches[1].compatible
    assert not result.matches[-1].compatible  # несовместимый — последний
    assert result.matches[0].score >= result.matches[1].score
    assert result.matches[0].cargo.payment_amount == Decimal(180000)


# ── Repository ───────────────────────────────────────────────────────────────


async def test_in_memory_repository() -> None:
    repo = InMemoryCargoRepository()
    cargo = _cargo()
    await repo.save(cargo)

    assert await repo.get(cargo.id) == cargo
    assert await repo.get("нет") is None
    assert len(await repo.search(_query())) == 1
    assert len(await repo.find_by_region("Москва")) == 1
    assert await repo.find_by_region("Казань") == ()


# ── MatchingService: события и уведомления ───────────────────────────────────


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


async def test_end_to_end_raw_cargo_to_notification() -> None:
    """RawCargo → Normalizer → Repository → SearchEngine → Match → NC."""
    raw = RawCargo(
        external_id="ati-1",
        title="Мебель",
        url="https://ati.su/c/1",
        attributes={
            "weight": "4,5 т",
            "volume": "25 м3",
            "length": "5 м",
            "width": "2 м",
            "height": "2,2 м",
            "loading_region": "москва",
            "unloading_region": "Санкт-Петербург",
            "price": "120 000 ₽",
            "distance_km": "700",
        },
    )
    cargo = CargoNormalizer().normalize(raw, "ati")

    repo = InMemoryCargoRepository()
    await repo.save(cargo)
    await repo.save(_cargo(weight_kg=9000))  # несовместимый сосед

    bus = EventBus()
    matched: list[CargoMatched] = []
    rejected: list[CargoRejected] = []
    completed: list[SearchCompleted] = []
    bus.subscribe(CargoMatched, matched.append)
    bus.subscribe(CargoRejected, rejected.append)
    bus.subscribe(SearchCompleted, completed.append)
    sender = _FakeSender()

    service = CargoMatchingService(
        engine=_engine(), repository=repo, event_bus=bus, notifications=sender
    )
    best = await service.find_best(MAN_TGL)

    assert best is not None and best.cargo_id == "ati-1"
    assert best.compatible and best.compatibility_result.score == 100
    # события с trace_id
    assert len(matched) == 1 and matched[0].cargo_id == "ati-1"
    assert len(rejected) == 1
    assert len(completed) == 1 and completed[0].matched == 1
    assert matched[0].trace_id == completed[0].trace_id
    # уведомление: категория CARGO, маршрут, вес, цена, совместимость, ссылка
    assert len(sender.sent) == 1
    notification = sender.sent[0]
    assert notification.category.value == "cargo"
    assert "Москва → Санкт-Петербург" in notification.body
    assert "4500 кг" in notification.body
    assert "120000 ₽" in notification.body
    assert "Совместимость: 100%" in notification.body
    assert notification.actions[0].url == "https://ati.su/c/1"
    assert notification.trace_id == completed[0].trace_id


async def test_match_single_service() -> None:
    service = CargoMatchingService(
        engine=_engine(),
        repository=InMemoryCargoRepository(),
        event_bus=EventBus(),
        notifications=_FakeSender(),
    )
    match = service.match_single(_cargo(), MAN_TGL)
    assert match.compatible
