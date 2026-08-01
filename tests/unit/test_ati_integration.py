"""Тесты Stage 9.5 — production ATI: auth, клиент, mapper, дедуп, конвейер."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.buses import EventBus
from app.core.errors import (
    SourceAuthenticationError,
    SourceParsingError,
    SourceRateLimitError,
    SourceUnavailableError,
)
from app.core.events import CargoReceived
from app.core.models.history import HistoryEntry
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.notification import Notification, NotificationCategory
from app.core.models.settings import AppSettings
from app.infrastructure.routes import MockRouteProvider
from app.infrastructure.sources.ati import AtiAuthProvider, AtiCargoMapper, AtiClient, AtiSource
from app.infrastructure.sources.ati.demo import (
    DEMO_CREDENTIALS_REFERENCE,
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
from app.services.monitoring import AnalyticsCollector
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
    CargoDeduplicator,
    CargoNormalizer,
    SourceRegistry,
    SourceRuntime,
    cargo_fingerprint,
)
from app.ui.viewmodels import mock_vehicle


class _CredStore:
    """Учётки в памяти (тестовая реализация порта)."""

    def __init__(self, values: dict[tuple[str, str], str] | None = None) -> None:
        self._values = values or {}

    def get(self, credentials_reference: str, field: str) -> str | None:
        return self._values.get((credentials_reference, field))


def _client(handler: Any, creds: _CredStore | None = None) -> AtiClient:
    provider = creds if creds is not None else _CredStore({("ref", "api_key"): "k-static"})
    return AtiClient(provider, transport=httpx.MockTransport(handler))


# ── Authentication ───────────────────────────────────────────────────────────


async def test_auth_static_api_key_without_http() -> None:
    provider = AtiAuthProvider(_CredStore({("ref", "api_key"): "k-static"}))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as http:
        token = await provider.token(http, "ref")
    assert token == "k-static"  # HTTP не понадобился


async def test_auth_session_login_caches_and_refreshes() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access_token": f"t-{calls}", "expires_in": 100})

    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    provider = AtiAuthProvider(
        _CredStore({("ref", "login"): "user", ("ref", "password"): "pass"}),
        clock=lambda: now,
    )
    async with httpx.AsyncClient(
        base_url="https://api.ati.su", transport=httpx.MockTransport(handler)
    ) as http:
        first = await provider.token(http, "ref")
        second = await provider.token(http, "ref")  # из кеша
        assert first == second == "t-1" and calls == 1

        now = now + timedelta(seconds=90)  # осталось 10 c < зазора 60 — обновляем
        third = await provider.token(http, "ref")
        assert third == "t-2" and calls == 2

        provider.invalidate("ref")
        fourth = await provider.token(http, "ref")
        assert fourth == "t-3" and calls == 3


async def test_auth_missing_credentials_raises() -> None:
    provider = AtiAuthProvider(_CredStore())
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as http:
        with pytest.raises(SourceAuthenticationError, match="не настроены"):
            await provider.token(http, "ref")


async def test_client_reauths_once_on_401() -> None:
    """401 → инвалидация токена → новый токен → повтор запроса."""
    tokens_issued = 0
    search_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tokens_issued
        if request.url.path == "/auth/v1.0/token":
            tokens_issued += 1
            return httpx.Response(200, json={"access_token": f"t-{tokens_issued}"})
        search_calls.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer t-1":
            return httpx.Response(401)  # первый токен «протух»
        return httpx.Response(200, json={"loads": [{"id": "x"}]})

    client = _client(handler, _CredStore({("ref", "login"): "u", ("ref", "password"): "p"}))
    loads = await client.search_cargo(credentials_reference="ref", max_results=10, filters={})
    await client.aclose()
    assert [load["id"] for load in loads] == ["x"]
    assert tokens_issued == 2
    assert search_calls == ["Bearer t-1", "Bearer t-2"]


async def test_client_maps_403_and_429() -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    client = _client(forbidden)
    with pytest.raises(SourceAuthenticationError):
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()

    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"})

    client = _client(limited)
    with pytest.raises(SourceRateLimitError) as info:
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()
    assert info.value.retry_after == 17.0


async def test_client_retries_5xx_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.infrastructure.sources.ati.client._TRANSPORT_BACKOFF", 0.0)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    client = _client(handler)
    with pytest.raises(SourceUnavailableError, match="503"):
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()
    assert attempts == 3  # транспортные повторы


async def test_client_timeout_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.infrastructure.sources.ati.client._TRANSPORT_BACKOFF", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("боевая сеть недоступна")

    client = _client(handler)
    with pytest.raises(SourceUnavailableError, match="вовремя"):
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()


async def test_client_invalid_json_raises_parsing_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    client = _client(handler)
    with pytest.raises(SourceParsingError):
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()


async def test_client_paginates_until_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.infrastructure.sources.ati.client._PER_PAGE", 2)
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as jsonlib

        body = jsonlib.loads(request.content.decode())
        page = int(body["page"])
        pages.append(page)
        assert body["per_page"] == 2
        loads = [{"id": f"p{page}-{i}"} for i in range(2)] if page <= 3 else []
        return httpx.Response(200, json={"loads": loads})

    client = _client(handler)
    loads = await client.search_cargo(credentials_reference="ref", max_results=5, filters={})
    await client.aclose()
    assert len(loads) == 5  # 2+2+2 → срез до max_results
    assert pages == [1, 2, 3]


async def test_client_filters_go_into_request_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as jsonlib

        captured.update(jsonlib.loads(request.content.decode()))
        return httpx.Response(200, json={"loads": []})

    client = _client(handler)
    await client.search_cargo(
        credentials_reference="ref",
        max_results=10,
        filters={
            "regions": "Москва, Московская область",
            "min_weight": "1000",
            "max_weight": "20000",
            "min_price": "50000",
            "cargo_types": "мебель",
        },
    )
    await client.aclose()
    assert captured["from_cities"] == ["Москва", "Московская область"]
    assert captured["weight_min_tons"] == 1.0 and captured["weight_max_tons"] == 20.0
    assert captured["rate_min"] == 50000.0
    assert captured["cargo_types"] == ["мебель"]


# ── Mapper и нормализация реальных форматов ──────────────────────────────────


def test_mapper_nested_real_payload_preserves_everything() -> None:
    payload = {
        "id": "ati-42",
        "cargo": {
            "name": "Мебель",
            "weight": {"quantity": 5.5, "type": "tons"},
            "sizes": "6.2x2.45x2.5",
            "volume": "38 м3",
            "pallets": 14,
        },
        "loading": {"city_name": "Москва", "date": "2026-08-01"},
        "unloading": {"city_name": "Санкт-Петербург", "date_to": "2026-08-03"},
        "payment": {"rate_text": "120 000 руб"},
        "car_type": "тент",
        "distance": 710,
        "url": "https://ati.su/cargo/42",
        "неизвестное_поле": {"вложенное": True},
    }
    raw = AtiCargoMapper().map(payload)

    assert raw.external_id == "ati-42"
    assert raw.attributes["weight"] == "5.5 т"
    # комбинированные габариты — без навязанной единицы (решает нормализатор)
    assert raw.attributes["length"] == "6.2"
    assert raw.attributes["width"] == "2.45"
    assert raw.attributes["height"] == "2.5"
    assert raw.attributes["volume"] == "38 м3"
    assert raw.attributes["pallets"] == "14"
    assert raw.attributes["price"] == "120 000 руб"
    assert raw.attributes["loading_date"] == "2026-08-01"
    assert raw.attributes["delivery_deadline"] == "2026-08-03"
    assert raw.raw["неизвестное_поле"] == {"вложенное": True}  # raw_metadata не теряется

    cargo = CargoNormalizer().normalize(raw, "ati")
    assert cargo.weight_kg == 5500
    assert cargo.length_cm == 620 and cargo.width_cm == 245 and cargo.height_cm == 250
    assert cargo.volume_m3 == 38.0
    assert cargo.pallet_count == 14
    assert cargo.payment_amount == Decimal(120000)
    assert cargo.loading_region == "Москва" and cargo.unloading_region == "Санкт-Петербург"


def test_normalizer_real_ati_weight_formats() -> None:
    normalizer = CargoNormalizer()

    def weight(text: str) -> int | None:
        raw = AtiCargoMapper().map({"id": "w", "cargo": {"weight": text}})
        return normalizer.normalize(raw, "ati").weight_kg

    assert weight("5 т") == 5000
    assert weight("5000 кг") == 5000
    assert weight("5.5 тонн") == 5500


def test_mapper_tolerates_garbage_payload() -> None:
    raw = AtiCargoMapper().map({"cargo": "не словарь", "loading": None, "payment": []})
    cargo = CargoNormalizer().normalize(raw, "ati")
    assert cargo.weight_kg is None and cargo.payment_amount is None
    assert cargo.source_id == "ati"  # битая карточка не роняет конвейер


# ── Дедупликация ─────────────────────────────────────────────────────────────


def _cargo_pair() -> tuple[Any, Any]:
    raw = AtiCargoMapper().map(
        {
            "id": "dup-1",
            "cargo": {"weight": "5 т"},
            "loading": {"city_name": "Москва"},
            "unloading": {"city_name": "Тверь"},
            "payment": {"rate_sum": 35000},
        }
    )
    normalizer = CargoNormalizer()
    return normalizer.normalize(raw, "ati"), normalizer.normalize(raw, "ati")


def test_fingerprint_stable_and_price_sensitive() -> None:
    first, second = _cargo_pair()
    assert cargo_fingerprint(first) == cargo_fingerprint(second)
    from dataclasses import replace

    changed = replace(first, payment_amount=Decimal(40000))
    assert cargo_fingerprint(changed) != cargo_fingerprint(first)  # новая цена — новое предложение


def test_deduplicator_registers_once_with_lru_bound() -> None:
    dedup = CargoDeduplicator(capacity=2)
    first, second = _cargo_pair()
    assert dedup.register(first) is True
    assert dedup.register(second) is False  # дубликат
    from dataclasses import replace

    b = replace(first, id="b")
    c = replace(first, id="c")
    assert dedup.register(b) and dedup.register(c)
    assert len(dedup) == 2  # LRU вытеснил самый старый
    assert dedup.register(first) is True  # вытеснен — считается новым


# ── Runtime, Scheduler, события ──────────────────────────────────────────────


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class _History:
    def __init__(self) -> None:
        self.entries: list[HistoryEntry] = []

    async def add(self, entry: HistoryEntry) -> None:
        self.entries.append(entry)


def _runtime(bus: EventBus, sender: _Sender) -> SourceRuntime:
    client, _ = build_demo_ati_client()
    registry = SourceRegistry(bus)
    registry.register(AtiSource(DemoAtiCredentialProvider(), client=client))
    return SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=bus,
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        configurations=DemoAtiConfigurationRepository(),
    )


def test_scheduler_gets_ati_poll_job_with_config_interval() -> None:
    runtime = _runtime(EventBus(), _Sender())
    jobs = runtime.build_jobs()
    assert len(jobs) == 1
    spec = jobs[0].spec
    assert spec.name == "source:ati"
    assert getattr(spec.schedule, "seconds", None) == 300.0  # каждые 5 минут


async def test_run_source_publishes_cargo_received_with_trace() -> None:
    bus = EventBus()
    received: list[CargoReceived] = []
    bus.subscribe(CargoReceived, received.append)
    runtime = _runtime(bus, _Sender())

    report = await runtime.run_source("ati", trace_id="t-ati")

    assert report.success and report.trace_id == "t-ati"
    assert len(received) == 1
    assert received[0].source_id == "ati" and received[0].trace_id == "t-ati"
    assert len(received[0].items) == 5  # 4 уникальных + 1 дубль (дедуп — в пайплайне)


async def test_source_without_credentials_fails_with_notification() -> None:
    bus = EventBus()
    sender = _Sender()
    registry = SourceRegistry(bus)
    registry.register(AtiSource(_CredStore()))  # учёток нет
    config = DemoAtiConfigurationRepository()
    runtime = SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=bus,
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        configurations=config,
    )

    report = await runtime.run_source("ati")

    assert not report.success
    assert report.error is not None and "не настроены" in report.error
    assert sender.sent and "не удалось получить грузы" in sender.sent[0].title


# ── Полный конвейер: Mock ATI → Cargo → Matching → Notification ─────────────


async def test_full_pipeline_from_mock_ati_to_notification() -> None:
    bus = EventBus()
    sender = _Sender()
    runtime = _runtime(bus, sender)
    repository = InMemoryCargoRepository()
    collector = AnalyticsCollector()
    collector.attach(bus)

    matching_service = CargoMatchingService(
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
    ranked_batches: list[tuple[Any, ...]] = []
    vehicle = mock_vehicle()
    pipeline = RecommendationPipeline(
        repository=repository,
        matching=matching_service,
        intelligent=intelligent,
        deduplicator=CargoDeduplicationService(),
        vehicle_provider=lambda: vehicle,
        driver_provider=lambda: DriverProfile.create(home_region="Москва"),
        location_provider=lambda: "Москва",
        on_ranked=ranked_batches.append,
        duplicates_sink=collector.record_duplicates,
    )
    pipeline.attach(bus)

    report = await runtime.run_source("ati", trace_id="t-full")
    await pipeline.wait_idle()

    assert report.success
    result = pipeline.last_report
    assert result is not None
    assert result.received == 5 and result.new_count == 4 and result.duplicates == 1
    assert result.compatible == 3  # 20-тонник отсеян по совместимости
    assert result.best_route == "Москва → Санкт-Петербург"
    assert result.best_score > 0  # AI Score рассчитан

    # уведомление о лучшем грузе — категория ROUTE, деньги посчитаны
    route_notifications = [n for n in sender.sent if n.category is NotificationCategory.ROUTE]
    assert len(route_notifications) == 1
    body = route_notifications[0].body
    assert "Москва → Санкт-Петербург" in body and "Чистая прибыль" in body
    assert route_notifications[0].trace_id == "t-full"

    # дашборд получил карточки, лучшая — первой
    assert ranked_batches and ranked_batches[0][0].cargo_match.cargo.id == "ati-spb-120"

    # аналитика: дубликаты, средняя цена, направления
    assert collector.duplicate_counts["ati"] == 1
    assert collector.source_analytics("ati").duplicate_count == 1
    assert collector.average_price("ati") > 0
    assert "Москва → Санкт-Петербург" in collector.top_routes("ati")

    # повторный опрос: всё дубликаты, новый подбор не запускается
    await runtime.run_source("ati", trace_id="t-again")
    await pipeline.wait_idle()
    second = pipeline.last_report
    assert second is not None and second.new_count == 0 and second.duplicates == 5


# ── Безопасность ─────────────────────────────────────────────────────────────


async def test_token_never_leaks_into_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    secret = "super-secret-token-value-123"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1.0/token":
            return httpx.Response(200, json={"access_token": secret})
        return httpx.Response(200, json={"loads": []})

    client = _client(handler, _CredStore({("ref", "login"): "u", ("ref", "password"): "p"}))
    await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.verify(credentials_reference="ref")
    await client.aclose()

    assert secret not in caplog.text
    assert "Authorization" not in caplog.text


def test_no_hardcoded_secrets_in_codebase() -> None:
    """grep проекта: в app/ нет захардкоженных секретов."""
    import re
    from pathlib import Path

    pattern = re.compile(r"""(?:TOKEN|PASSWORD|API_KEY|SECRET)\s*=\s*["'][A-Za-z0-9_\-]{16,}["']""")
    offenders: list[str] = []
    for path in Path(__file__).resolve().parents[2].joinpath("app").rglob("*.py"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "not-a-secret" not in line:
                offenders.append(f"{path.name}:{line_number}: {line.strip()}")
    assert offenders == [], f"похоже на захардкоженные секреты: {offenders}"


def test_demo_configuration_matches_spec_example() -> None:
    """Конфигурация из ТЗ: имя, регионы, вес — через SourceConfiguration."""
    config = DemoAtiConfigurationRepository().get("ati")
    assert config is not None
    assert config.name == "ATI Москва" and config.enabled
    assert config.credentials_reference == DEMO_CREDENTIALS_REFERENCE
    assert "Москва" in config.filters["regions"]
    assert config.filters["min_weight"] == "1000"
    assert config.filters["max_weight"] == "20000"
    assert config.polling_interval_seconds == 300
