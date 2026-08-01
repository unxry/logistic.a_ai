"""Нагрузочный тест Stage 9.6: 1000 грузов ATI через весь конвейер.

Проверяется: время обработки, память (tracemalloc), дедупликация,
совместимые грузы, лучшая рекомендация и сквозной trace_id.
"""

from __future__ import annotations

import time
import tracemalloc
from typing import Any

import httpx

from app.buses import EventBus
from app.core.events import BestCargoSelected, CargoReceived
from app.core.models.history import HistoryEntry
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.notification import Notification, NotificationCategory
from app.core.models.settings import AppSettings
from app.core.models.sources import SourceConfiguration
from app.infrastructure.routes import MockRouteProvider
from app.infrastructure.sources.ati import AtiClient, AtiSource
from app.infrastructure.sources.ati.auth import TOKEN_PATH
from app.infrastructure.sources.ati.client import SEARCH_PATH
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
    SourceRegistry,
    SourceRuntime,
)
from app.ui.viewmodels import mock_vehicle

TOTAL_LOADS = 1000
DUPLICATE_EVERY = 7  # каждый 7-й груз — дубль предыдущего (~13%)

_CITIES = ("Санкт-Петербург", "Казань", "Нижний Новгород", "Воронеж", "Тверь")


def generate_loads(total: int) -> list[dict[str, Any]]:
    """Детерминированные реалистичные payload'ы ATI с дублями."""
    loads: list[dict[str, Any]] = []
    for index in range(total):
        if index % DUPLICATE_EVERY == 0 and loads:
            loads.append(dict(loads[-1]))  # точный дубль предыдущего
            continue
        city = _CITIES[index % len(_CITIES)]
        weight_tons = 1.5 + (index % 9) * 0.5  # 1.5 … 5.5 т
        price = 30000 + (index % 40) * 1500  # 30 000 … 88 500 ₽
        loads.append(
            {
                "id": f"ati-load-{index}",
                "cargo": {
                    "name": "Груз",
                    "weight": f"{weight_tons} т",
                    "sizes": "4.8x2.0x2.1",
                },
                "loading": {"city_name": "Москва"},
                "unloading": {"city_name": city},
                "payment": {"rate_sum": price},
                "car_type": "тент",
                "distance": 200 + (index % 15) * 40,
            }
        )
    # эталонный лучший груз — заведомо максимальная экономика
    loads[len(loads) // 2] = {
        "id": "ati-load-best",
        "cargo": {"name": "Лучший", "weight": "5 т", "sizes": "5.0x2.0x2.2"},
        "loading": {"city_name": "Москва"},
        "unloading": {"city_name": "Санкт-Петербург"},
        "payment": {"rate_text": "150 000 руб"},
        "car_type": "тент",
        "distance": 700,
    }
    return loads[:total]


class _BulkAtiApi:
    """Мок ATI, отдающий сгенерированные грузы страницами по 50."""

    def __init__(self, loads: list[dict[str, Any]]) -> None:
        self._loads = loads

    def handler(self, request: httpx.Request) -> httpx.Response:
        import json as jsonlib

        if request.url.path == TOKEN_PATH:
            return httpx.Response(200, json={"access_token": "load-test", "expires_in": 3600})
        if request.url.path == SEARCH_PATH:
            body = jsonlib.loads(request.content.decode())
            page = int(body["page"])
            per_page = int(body["per_page"])
            start = (page - 1) * per_page
            return httpx.Response(200, json={"loads": self._loads[start : start + per_page]})
        return httpx.Response(404)


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class _History:
    async def add(self, entry: HistoryEntry) -> None:
        return None


class _Config:
    def __init__(self) -> None:
        self._configuration = SourceConfiguration.create(
            "ati",
            name="ATI load test",
            enabled=True,
            credentials_reference="load",
            max_results=TOTAL_LOADS,
        )

    def get(self, source_id: str) -> SourceConfiguration | None:
        return self._configuration if source_id == "ati" else None

    def get_all(self) -> tuple[SourceConfiguration, ...]:
        return (self._configuration,)

    def save(self, configuration: SourceConfiguration) -> None:
        return None

    def delete(self, source_id: str) -> None:
        return None

    def enable(self, source_id: str) -> None:
        return None

    def disable(self, source_id: str) -> None:
        return None


class _Creds:
    def get(self, credentials_reference: str, field: str) -> str | None:
        return "load-test-static-key" if field == "api_key" else None


async def test_thousand_loads_full_pipeline() -> None:
    loads = generate_loads(TOTAL_LOADS)
    bus = EventBus()
    sender = _Sender()
    best_events: list[BestCargoSelected] = []
    received: list[CargoReceived] = []
    bus.subscribe(BestCargoSelected, best_events.append)
    bus.subscribe(CargoReceived, received.append)

    client = AtiClient(_Creds(), transport=httpx.MockTransport(_BulkAtiApi(loads).handler))
    registry = SourceRegistry(bus)
    registry.register(AtiSource(_Creds(), client=client))
    runtime = SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=bus,
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        configurations=_Config(),
        failure_cooldown=NotificationCooldownPolicy(),
    )
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
    pipeline = RecommendationPipeline(
        repository=repository,
        matching=matching,
        intelligent=intelligent,
        deduplicator=CargoDeduplicationService(capacity=TOTAL_LOADS * 2),
        vehicle_provider=lambda: vehicle,
        driver_provider=lambda: DriverProfile.create(home_region="Москва"),
        location_provider=lambda: "Москва",
        event_publisher=bus,
    )
    pipeline.attach(bus)

    tracemalloc.start()
    started = time.perf_counter()
    report = await runtime.run_source("ati", trace_id="t-load")
    await pipeline.wait_idle()
    elapsed_ms = (time.perf_counter() - started) * 1000
    _, memory_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert report.success and len(report.items) == TOTAL_LOADS  # получено 1000
    result = pipeline.last_report
    assert result is not None and result.trace_id == "t-load"  # trace сквозной
    assert result.received == TOTAL_LOADS
    expected_duplicates = sum(1 for i in range(TOTAL_LOADS) if i % DUPLICATE_EVERY == 0 and i > 0)
    assert result.duplicates == expected_duplicates
    assert result.new_count == TOTAL_LOADS - expected_duplicates
    assert result.compatible > 500  # большинство грузов подходят под MAN TGL
    assert result.best_cargo_id == "ati-load-best"  # лучший найден корректно
    assert result.best_score > 0

    # события и уведомление несут тот же trace
    assert best_events and best_events[0].trace_id == "t-load"
    route_notifications = [n for n in sender.sent if n.category is NotificationCategory.ROUTE]
    assert route_notifications and route_notifications[0].trace_id == "t-load"

    # производительность: конвейер на 1000 грузов — секунды, не минуты
    assert elapsed_ms < 30_000, f"слишком медленно: {elapsed_ms:.0f} мс"
    assert memory_peak < 256 * 1024 * 1024, f"слишком много памяти: {memory_peak / 2**20:.1f} МиБ"
