"""Benchmark конвейера грузов: 1000 payload'ов ATI до рекомендации.

Запуск:
    uv run python scripts/cargo_pipeline_benchmark.py [--total 1000]

Печатает сводку по формату ТЗ Stage 9.6: получено / нормализовано /
дубликаты / подходящих / среднее время на груз + память и этапы.
Использует те же генератор и мок-транспорт, что и нагрузочный тест
(tests/unit/test_ati_load.py) — цифры воспроизводимы.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.buses import EventBus
from app.core.models.history import HistoryEntry
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.notification import Notification
from app.core.models.settings import AppSettings
from app.infrastructure.routes import MockRouteProvider
from app.infrastructure.sources.ati import AtiClient, AtiSource
from app.infrastructure.storage.in_memory_cargo import InMemoryCargoRepository
from app.services.logistics.compatibility_service import CargoCompatibilityService
from app.services.matching import (
    CargoProfitCalculator,
    IntelligentMatchingService,
    PreferenceEngine,
    RouteScoreCalculator,
)
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
from tests.unit.test_ati_load import (
    _BulkAtiApi,
    _Config,
    _Creds,
    generate_loads,
)


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class _History:
    async def add(self, entry: HistoryEntry) -> None:
        return None


async def run_benchmark(total: int) -> None:
    """Прогнать конвейер и напечатать сводку."""
    loads = generate_loads(total)
    bus = EventBus()
    sender = _Sender()
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
        deduplicator=CargoDeduplicationService(capacity=total * 2),
        vehicle_provider=lambda: vehicle,
        driver_provider=lambda: DriverProfile.create(home_region="Москва"),
        location_provider=lambda: "Москва",
        event_publisher=bus,
    )
    pipeline.attach(bus)

    tracemalloc.start()
    fetch_started = time.perf_counter()
    report = await runtime.run_source("ati", trace_id="bench")
    fetch_ms = (time.perf_counter() - fetch_started) * 1000
    pipeline_started = time.perf_counter()
    await pipeline.wait_idle()
    pipeline_ms = (time.perf_counter() - pipeline_started) * 1000
    _, memory_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    await client.aclose()

    result = pipeline.last_report
    assert result is not None
    total_ms = fetch_ms + pipeline_ms
    print("── Cargo Pipeline Benchmark ─────────────────────────────")
    print(f"Получено:        {result.received}")
    print(f"Нормализовано:   {len(report.items)}")
    print(f"Дубликаты:       {result.duplicates}")
    print(f"Обновления:      {result.updated_count}")
    print(f"Подходящих:      {result.compatible}")
    print(f"Лучший груз:     {result.best_route} · AI Score {result.best_score}")
    print(f"trace_id:        {result.trace_id} (сквозной)")
    print("── Время ────────────────────────────────────────────────")
    print(f"Fetch+нормализация: {fetch_ms:>8.0f} ms")
    print(f"Дедуп+подбор:       {pipeline_ms:>8.0f} ms")
    print(f"Всего:              {total_ms:>8.0f} ms")
    print(f"Среднее время:      {total_ms / max(1, result.received):>8.2f} ms/груз")
    print(f"Пик памяти:         {memory_peak / 2**20:>8.1f} МиБ")


def main() -> None:
    """CLI-обёртка."""
    parser = argparse.ArgumentParser(description="Benchmark конвейера LogistAI")
    parser.add_argument("--total", type=int, default=1000, help="сколько грузов прогнать")
    arguments = parser.parse_args()
    asyncio.run(run_benchmark(arguments.total))


if __name__ == "__main__":
    main()
