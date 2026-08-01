"""Тесты presentation-слоя (Stage 8.6): форматирование, карточки, дашборд.

ViewModel'и не знают Qt (закреплено контрактом import-linter и
subprocess-проверкой ниже) и получают данные только через порты.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.buses import EventBus
from app.core.events import CargoReceived, SourceHealthChanged, TelegramStatusChanged
from app.core.models.analytics import MatchingAnalytics
from app.core.models.connection import ConnectionState
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.matching import MatchingContext
from app.core.models.search import CargoSearchQuery
from app.core.models.severity import Severity
from app.core.models.sources import SourceHealth, SourceStatus
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
from app.ui.viewmodels import (
    MOCK_NOW,
    AnalyticsViewModel,
    BadgeTone,
    CargoCardViewModel,
    CargoRecommendationChanged,
    DashboardUpdated,
    DashboardViewModel,
    EventRowViewModel,
    MockDashboardDataProvider,
    SourceStatusChanged,
    SourceStatusViewModel,
    VehicleViewModel,
    mock_best_matches,
    mock_vehicle,
    telegram_status_badge,
)
from app.ui.viewmodels.formatting import (
    EMPTY,
    dimensions_cm,
    distance_km,
    money,
    rate_per_km,
    relative_time,
    weight_kg,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── Форматирование ───────────────────────────────────────────────────────────


def test_money_and_rate_formatting() -> None:
    assert money(Decimal(120000)) == "120 000 ₽"
    assert money(Decimal(-15000)) == "-15 000 ₽"
    assert rate_per_km(Decimal("119.72")) == "120 ₽/км"


def test_physical_formatting_with_missing_data() -> None:
    assert weight_kg(5000) == "5 000 кг"
    assert weight_kg(None) == EMPTY
    assert dimensions_cm(500, 200, 220) == "500 × 200 × 220 см"
    assert dimensions_cm(500, None, 220) == EMPTY
    assert distance_km(710.0) == "710 км"
    assert distance_km(None) == EMPTY


def test_relative_time_buckets() -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    assert relative_time(now - timedelta(seconds=10), now) == "только что"
    assert relative_time(now - timedelta(minutes=5), now) == "5 мин назад"
    assert relative_time(now - timedelta(hours=3), now) == "3 ч назад"
    assert relative_time(now - timedelta(days=2), now) == "29.07"


# ── Карточки ─────────────────────────────────────────────────────────────────


async def _best_match_from_pipeline_async() -> Any:
    """Реальный конвейер: поиск → интеллектуальный подбор → лучший груз."""
    vehicle = mock_vehicle()
    cargo = Cargo(
        id="cargo-spb",
        source_id="test",
        url="https://ati.su/c/1",
        weight_kg=5000,
        length_cm=500,
        width_cm=200,
        height_cm=220,
        volume_m3=25.0,
        loading_region="Москва",
        unloading_region="Санкт-Петербург",
        payment_amount=Decimal(120000),
        distance_km=700.0,
    )
    engine = CargoSearchEngine(
        prefilter=CargoPreFilter(),
        compatibility=CargoCompatibilityService(BasicCompatibilityChecker()),
        scorer=CargoScoreCalculator(),
        ranking=CargoRankingService(),
    )
    match = engine.match_single(cargo, vehicle, CargoSearchQuery.create(vehicle.id))
    bus = EventBus()

    class _Sink:
        async def send(self, notification: Any) -> None:  # pragma: no cover - не зовётся
            return None

    service = IntelligentMatchingService(
        preferences=PreferenceEngine(),
        profit=CargoProfitCalculator(),
        routes=RouteService(
            provider=MockRouteProvider(), costs=RouteCostCalculator(), event_bus=bus
        ),
        route_score=RouteScoreCalculator(),
        event_bus=bus,
        notifications=_Sink(),
    )
    context = MatchingContext(
        vehicle_profile=vehicle,
        driver_profile=DriverProfile.create(home_region="Москва"),
        current_location="Москва",
    )
    best = await service.select_best((match,), context)
    assert best is not None
    return best


def _best_match_from_pipeline() -> Any:
    """Синхронная обёртка конвейера для не-async тестов."""
    import asyncio

    return asyncio.run(_best_match_from_pipeline_async())


def test_cargo_card_from_real_pipeline() -> None:
    """Карточка эталона ТЗ: 710 км, 120 000 ₽ дохода, 85 000 ₽ чистыми."""
    card = CargoCardViewModel.from_match(_best_match_from_pipeline())
    assert card.cargo_id == "cargo-spb"
    assert card.route == "Москва → Санкт-Петербург"
    assert card.distance == "710 км"
    assert card.weight == "5 000 кг"
    assert card.dimensions == "500 × 200 × 220 см"
    assert card.price == "120 000 ₽"
    assert card.profit == "85 000 ₽"
    assert card.profit_per_km == "120 ₽/км"
    assert card.compatibility == 100 and card.score >= 70
    assert card.explanation and any("Прибыль" in line for line in card.explanation)
    assert card.actions[0].url == "https://ati.su/c/1"


def test_cargo_card_tolerates_missing_data() -> None:
    """Пустая карточка честно показывает тире, а не выдуманные значения."""
    best = _best_match_from_pipeline()
    bare_cargo = Cargo(id="c-bare", source_id="test")
    from dataclasses import replace

    bare = replace(
        best,
        cargo_match=replace(best.cargo_match, cargo=bare_cargo),
        profit=None,
        route_estimate=None,
    )
    card = CargoCardViewModel.from_match(bare)
    assert card.route == EMPTY
    assert card.weight == EMPTY and card.dimensions == EMPTY
    assert card.price == EMPTY and card.profit == EMPTY
    assert card.profit_per_km == "" and card.actions == ()


def test_source_status_from_health() -> None:
    now = MOCK_NOW
    online = SourceStatusViewModel.from_health(
        "ati",
        "ATI.SU",
        SourceHealth(status=SourceStatus.ONLINE, last_success=now - timedelta(minutes=5)),
        cargo_count=542,
        now=now,
    )
    assert online.status.tone is BadgeTone.OK and online.status.label == "В сети"
    assert online.last_sync == "5 мин назад" and online.cargo_count == 542

    failed = SourceStatusViewModel.from_health(
        "ozon",
        "Ozon",
        SourceHealth(status=SourceStatus.FAILED, last_error="HTTP 503", consecutive_failures=4),
        cargo_count=0,
        now=now,
    )
    assert failed.status.tone is BadgeTone.ERROR
    assert failed.errors == "HTTP 503" and failed.consecutive_failures == 4
    assert failed.last_sync == "ещё не синхронизировался"

    disabled = SourceStatusViewModel.from_health(
        "csv", "CSV", SourceHealth(status=SourceStatus.DISABLED), cargo_count=0, now=now
    )
    assert disabled.status.tone is BadgeTone.MUTED


def test_analytics_viewmodel_build_and_empty() -> None:
    stats = MatchingAnalytics(
        compatible_count=38,
        average_profit=Decimal(82500),
        best_routes=("Москва → Санкт-Петербург",),
    )
    vm = AnalyticsViewModel.build(
        found_count=641, statistics=stats, potential_profit=Decimal(160610)
    )
    assert vm.today_found == 641 and vm.matched_count == 38
    assert vm.potential_profit == "160 610 ₽"
    assert vm.best_route == "Москва → Санкт-Петербург"
    assert vm.average_profit == "82 500 ₽"

    empty = AnalyticsViewModel.empty()
    assert empty.today_found == 0
    assert empty.potential_profit == EMPTY and empty.best_route == EMPTY


def test_vehicle_and_event_row_viewmodels() -> None:
    vehicle = VehicleViewModel.from_profile(mock_vehicle())
    assert vehicle.name == "MAN TGL"
    assert vehicle.summary == "Тент · 6 000 кг · 38 м³ · 14 паллет"
    assert vehicle.dimensions == "620 × 245 × 250 см"

    entry = HistoryEntry(
        id="e1",
        occurred_at=MOCK_NOW - timedelta(minutes=4),
        kind=HistoryKind.NOTIFICATION,
        severity=Severity.SUCCESS,
        title="🚚 Лучший груз найден",
        source="matching",
    )
    row = EventRowViewModel.from_entry(entry, now=MOCK_NOW)
    assert row.title == "🚚 Лучший груз найден"
    assert row.time_label == "4 мин назад"
    assert row.severity == "success" and row.kind == "notification"


def test_telegram_badge_mapping() -> None:
    assert telegram_status_badge(ConnectionState.CONNECTED).label == "Подключён"
    error = telegram_status_badge(ConnectionState.ERROR, "401 Unauthorized")
    assert error.tone is BadgeTone.ERROR and error.detail == "401 Unauthorized"


# ── DashboardViewModel ───────────────────────────────────────────────────────


class Rig:
    """Дашборд на мок-провайдере с перехватом UI-событий."""

    def __init__(self) -> None:
        self.bus = EventBus()
        self.updated: list[DashboardUpdated] = []
        self.recommendations: list[CargoRecommendationChanged] = []
        self.source_changes: list[SourceStatusChanged] = []
        self.bus.subscribe(DashboardUpdated, self.updated.append)
        self.bus.subscribe(CargoRecommendationChanged, self.recommendations.append)
        self.bus.subscribe(SourceStatusChanged, self.source_changes.append)
        self.vm = DashboardViewModel(
            provider=MockDashboardDataProvider(),
            events=self.bus,
            clock=lambda: MOCK_NOW,
        )
        self.vm.attach()


async def test_dashboard_refresh_fills_everything() -> None:
    rig = Rig()
    assert rig.vm.application_status.label == "Запускается"

    snapshot = await rig.vm.refresh()

    assert snapshot.telegram_status.label == "Подключён"
    assert snapshot.active_vehicle is not None and snapshot.active_vehicle.name == "MAN TGL"
    assert {vm.id for vm in snapshot.sources_status} == {"ati", "ozon", "csv"}
    assert snapshot.analytics_summary.today_found == 641
    assert len(snapshot.recent_events) == 4
    # ozon FAILED → приложение работает с проблемами, причина названа
    assert snapshot.application_status.tone is BadgeTone.WARNING
    assert "Ozon Логистика: недоступен" in snapshot.application_status.detail
    assert len(rig.updated) == 1 and rig.updated[0].snapshot == snapshot


async def test_dashboard_reacts_to_domain_events() -> None:
    rig = Rig()
    await rig.vm.refresh()

    rig.bus.publish(TelegramStatusChanged(state=ConnectionState.ERROR, detail="сеть"))
    assert rig.vm.telegram_status.tone is BadgeTone.ERROR
    assert "Telegram: ошибка" in rig.vm.application_status.detail

    rig.bus.publish(SourceHealthChanged(source_id="ozon", status=SourceStatus.FAILED))
    assert rig.source_changes and rig.source_changes[-1].source.id == "ozon"
    assert rig.source_changes[-1].source.status.tone is BadgeTone.ERROR

    cargo = Cargo(id=uuid4().hex, source_id="ati")
    rig.bus.publish(CargoReceived(source_id="ati", trace_id="t", items=(cargo,)))
    assert rig.source_changes[-1].source.id == "ati"
    assert rig.vm.analytics_summary.today_found == 641  # счётчики читаются из провайдера


async def test_dashboard_recommendations_via_real_matching() -> None:
    rig = Rig()
    await rig.vm.refresh()
    best = await _best_match_from_pipeline_async()

    rig.vm.update_recommendations([best])

    assert len(rig.recommendations) == 1
    cards = rig.recommendations[0].cards
    assert cards[0].profit == "85 000 ₽"
    assert rig.vm.best_matches == cards
    assert rig.vm.analytics_summary.potential_profit == "85 000 ₽"


async def test_dashboard_mock_cards_and_detach() -> None:
    rig = Rig()
    await rig.vm.refresh()
    rig.vm.set_recommendation_cards(mock_best_matches(), potential_profit=Decimal(160610))
    assert rig.vm.analytics_summary.potential_profit == "160 610 ₽"
    assert len(rig.vm.best_matches) == 3

    rig.vm.detach()
    before = len(rig.updated)
    rig.bus.publish(TelegramStatusChanged(state=ConnectionState.DISCONNECTED))
    assert len(rig.updated) == before  # после detach дашборд молчит


# ── Чистота от Qt ────────────────────────────────────────────────────────────


def test_viewmodels_do_not_import_qt() -> None:
    """Импорт app.ui.viewmodels не тянет PySide6 (свежий интерпретатор)."""
    code = "import sys; import app.ui.viewmodels; assert 'PySide6' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
