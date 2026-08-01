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
from app.core.models.sources import AtiTokenState, SourceConfiguration, SourceContext, SourceStatus
from app.core.ports.source_credentials import CRED_ACCESS_TOKEN, CRED_TOKEN_EXPIRES_AT
from app.infrastructure.routes import MockRouteProvider
from app.infrastructure.sources.ati import AtiAuthProvider, AtiCargoMapper, AtiClient, AtiSource
from app.infrastructure.sources.ati.client import (
    BOARDS_CAN_VIEW_PATH,
    BOARDS_MY_PATH,
    BOARDS_PARTICIPATING_PATH,
    BYBOARDS_PATH,
    LOADS_PATH,
)
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


async def test_auth_access_token_state_valid_expiring_expired_missing() -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    provider = AtiAuthProvider(
        _CredStore(
            {
                ("valid", CRED_ACCESS_TOKEN): "valid-token-123456",
                ("valid", CRED_TOKEN_EXPIRES_AT): "2026-08-03T12:00:00+00:00",
                ("soon", CRED_ACCESS_TOKEN): "soon-token-123456",
                ("soon", CRED_TOKEN_EXPIRES_AT): "2026-08-02T06:00:00+00:00",
                ("expired", CRED_ACCESS_TOKEN): "expired-token-123456",
                ("expired", CRED_TOKEN_EXPIRES_AT): "2026-08-01T01:00:00+00:00",
            }
        ),
        clock=lambda: now,
    )
    assert provider.token_status("valid").state is AtiTokenState.VALID
    assert provider.token_status("soon").state is AtiTokenState.EXPIRING_SOON
    assert provider.token_status("expired").state is AtiTokenState.EXPIRED
    assert provider.token_status("missing").state is AtiTokenState.MISSING


async def test_auth_expired_access_token_is_not_used() -> None:
    provider = AtiAuthProvider(
        _CredStore(
            {
                ("ref", CRED_ACCESS_TOKEN): "expired-token-123456",
                ("ref", CRED_TOKEN_EXPIRES_AT): "2026-08-01T01:00:00+00:00",
            }
        ),
        clock=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as http:
        with pytest.raises(SourceAuthenticationError, match="истёк"):
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


async def test_client_owned_loads_uses_official_get_endpoint() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=[{"CargoId": "official-1"}])

    client = _client(handler)
    loads = await client.search_cargo(
        credentials_reference="ref",
        max_results=10,
        filters={"api_mode": "owned_loads"},
    )
    await client.aclose()
    assert loads == [{"CargoId": "official-1"}]
    assert calls == [("GET", LOADS_PATH)]
    assert client.last_pages_requested == 1


async def test_client_byboards_uses_official_carrier_endpoint() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer live-token-123456"
        return httpx.Response(200, json=[{"CargoId": "board-1"}, {"CargoId": "board-2"}])

    client = _client(
        handler,
        _CredStore({("ati_main", CRED_ACCESS_TOKEN): "live-token-123456"}),
    )
    loads = await client.search_cargo(
        credentials_reference="ati_main",
        max_results=1,
        filters={"api_mode": "byboards"},
    )
    await client.aclose()

    assert loads == [{"CargoId": "board-1"}]
    assert calls == [("GET", BYBOARDS_PATH)]
    assert client.last_pages_requested == 1


async def test_client_board_diagnostics_use_official_endpoints() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == BOARDS_CAN_VIEW_PATH:
            return httpx.Response(200, json=[{"id": "507f1f77bcf86cd799439011"}])
        if request.url.path == BOARDS_MY_PATH:
            return httpx.Response(200, json=["507f1f77bcf86cd799439012"])
        if request.url.path == BOARDS_PARTICIPATING_PATH:
            return httpx.Response(200, json=["507f1f77bcf86cd799439013"])
        return httpx.Response(404)

    client = _client(handler)
    can_view = await client.get_boards_can_view(credentials_reference="ref")
    my_ids = await client.get_my_board_ids(credentials_reference="ref")
    participating_ids = await client.get_participating_board_ids(credentials_reference="ref")
    await client.aclose()

    assert can_view == [{"id": "507f1f77bcf86cd799439011"}]
    assert my_ids == ["507f1f77bcf86cd799439012"]
    assert participating_ids == ["507f1f77bcf86cd799439013"]
    assert calls == [
        ("GET", BOARDS_CAN_VIEW_PATH),
        ("GET", BOARDS_MY_PATH),
        ("GET", BOARDS_PARTICIPATING_PATH),
    ]


async def test_ati_source_does_not_call_api_with_expired_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    client = AtiClient(
        _CredStore(
            {
                ("ati_main", CRED_ACCESS_TOKEN): "expired-token-123456",
                ("ati_main", CRED_TOKEN_EXPIRES_AT): "2026-08-01T01:00:00+00:00",
            }
        ),
        transport=httpx.MockTransport(handler),
        auth=AtiAuthProvider(
            _CredStore(
                {
                    ("ati_main", CRED_ACCESS_TOKEN): "expired-token-123456",
                    ("ati_main", CRED_TOKEN_EXPIRES_AT): "2026-08-01T01:00:00+00:00",
                }
            ),
            clock=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        ),
    )
    source = AtiSource(_CredStore(), client=client)
    context = SourceContext(
        logger=logging.getLogger("test"),
        settings=lambda: AppSettings(),
        configuration=SourceConfiguration.create(
            "ati",
            enabled=True,
            credentials_reference="ati_main",
            filters={"api_mode": "owned_loads"},
        ),
    )
    with pytest.raises(SourceAuthenticationError):
        await source.fetch(context)
    await client.aclose()
    assert calls == 0


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
    assert raw.url == "https://ati.su/cargo/42"

    cargo = CargoNormalizer().normalize(raw, "ati")
    assert cargo.weight_kg == 5500
    assert cargo.length_cm == 620 and cargo.width_cm == 245 and cargo.height_cm == 250
    assert cargo.volume_m3 == 38.0
    assert cargo.pallet_count == 14
    assert cargo.payment_amount == Decimal(120000)
    assert cargo.loading_region == "Москва" and cargo.unloading_region == "Санкт-Петербург"


def test_mapper_official_cargos_array_payload() -> None:
    payload = {
        "cargo_application_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "distance": 726,
        "route": {
            "loading": {"city_name": "Москва"},
            "unloading": {"city_name": "Казань"},
        },
        "cargos": [
            {
                "name": "Автомобиль(ли)",
                "weight": {"type": "tons", "quantity": 5.2},
                "volume": {"quantity": 36},
                "sizes": {
                    "length": {"value": 6.2},
                    "width": {"value": 2.45},
                    "height": {"value": 2.5},
                },
                "packaging": {"quantity": 12},
            }
        ],
        "TruePrice": 125000,
        "url": "https://loads.ati.su/cargos/3fa85f64-5717-4562-b3fc-2c963f66afa6",
    }
    raw = AtiCargoMapper().map(payload)
    assert raw.external_id == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert raw.title == "Автомобиль(ли)"
    assert raw.attributes["weight"] == "5.2 т"
    assert raw.attributes["length"] == "6.2 м"
    assert raw.attributes["width"] == "2.45 м"
    assert raw.attributes["height"] == "2.5 м"
    assert raw.attributes["price"] == "125000"
    assert raw.url == "https://loads.ati.su/cargos/3fa85f64-5717-4562-b3fc-2c963f66afa6"


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


class _ConfigRepo:
    def __init__(self, configuration: SourceConfiguration) -> None:
        self._configuration = configuration

    def get(self, source_id: str) -> SourceConfiguration | None:
        return self._configuration if source_id == self._configuration.source_id else None

    def list_enabled(self) -> tuple[SourceConfiguration, ...]:
        return (self._configuration,) if self._configuration.enabled else ()

    def save(self, configuration: SourceConfiguration) -> None:
        self._configuration = configuration


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


async def test_source_runtime_stops_ati_polling_when_token_expired() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"loads": [{"id": "should-not-happen"}]})

    creds = _CredStore(
        {
            ("ati_main", CRED_ACCESS_TOKEN): "expired-token-123456",
            ("ati_main", CRED_TOKEN_EXPIRES_AT): "2026-08-01T01:00:00+00:00",
        }
    )
    auth = AtiAuthProvider(creds, clock=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=UTC))
    client = AtiClient(creds, transport=httpx.MockTransport(handler), auth=auth)
    registry = SourceRegistry(EventBus())
    registry.register(AtiSource(creds, client=client))
    sender = _Sender()
    runtime = SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=EventBus(),
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        configurations=_ConfigRepo(
            SourceConfiguration.create(
                source_id="ati",
                name="ATI Live",
                enabled=True,
                credentials_reference="ati_main",
                filters={"api_mode": "owned_loads"},
            )
        ),
    )

    report = await runtime.run_source("ati", trace_id="expired-token-run")

    assert not report.success
    assert report.attempts == 0
    assert report.error is not None and "истёк" in report.error
    assert calls == 0
    assert any("Токен ATI истёк" in notification.title for notification in sender.sent)


async def test_zero_real_ati_cargos_marks_no_market_and_creates_no_cargo_notification() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == BYBOARDS_PATH
        return httpx.Response(200, json={"loads": []})

    bus = EventBus()
    sender = _Sender()
    repository = InMemoryCargoRepository()
    registry = SourceRegistry(bus)
    creds = _CredStore({("ref", "api_key"): "not-a-secret"})
    client = AtiClient(creds, transport=httpx.MockTransport(handler))
    registry.register(AtiSource(creds, client=client))
    runtime = SourceRuntime(
        registry=registry,
        normalizer=CargoNormalizer(),
        event_bus=bus,
        notifications=sender,
        history=_History(),
        settings_provider=AppSettings,
        configurations=_ConfigRepo(
            SourceConfiguration.create(
                source_id="ati",
                name="ATI Live",
                enabled=True,
                credentials_reference="ref",
                filters={"api_mode": "byboards"},
            )
        ),
    )
    pipeline = RecommendationPipeline(
        repository=repository,
        matching=CargoMatchingService(
            engine=CargoSearchEngine(
                prefilter=CargoPreFilter(),
                compatibility=CargoCompatibilityService(BasicCompatibilityChecker()),
                scorer=CargoScoreCalculator(),
                ranking=CargoRankingService(),
            ),
            repository=repository,
            event_bus=bus,
            notifications=sender,
        ),
        intelligent=IntelligentMatchingService(
            preferences=PreferenceEngine(),
            profit=CargoProfitCalculator(),
            routes=RouteService(
                provider=MockRouteProvider(), costs=RouteCostCalculator(), event_bus=bus
            ),
            route_score=RouteScoreCalculator(),
            event_bus=bus,
            notifications=sender,
        ),
        deduplicator=CargoDeduplicationService(),
        vehicle_provider=mock_vehicle,
        driver_provider=lambda: DriverProfile.create(home_region="Москва"),
        location_provider=lambda: "Москва",
    )
    pipeline.attach(bus)

    report = await runtime.run_source("ati", trace_id="zero-live")
    await pipeline.wait_idle()

    assert report.success and report.raw_count == 0 and report.items == ()
    assert runtime.health("ati").status is SourceStatus.AUTHENTICATED_NO_MARKET_ACCESS
    assert pipeline.last_report is None
    assert not any(
        notification.category in (NotificationCategory.CARGO, NotificationCategory.ROUTE)
        for notification in sender.sent
    )


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
    assert result.prefilter_rejected == 0
    assert result.compatible == 3  # 20-тонник отсеян по совместимости
    assert result.compatibility_rejected == 1
    assert result.ranked_count == 3
    assert result.notifications_created == 1
    assert result.best_route == "Москва → Санкт-Петербург"
    assert result.best_score > 0  # AI Score рассчитан

    # уведомление о лучшем грузе — категория ROUTE, деньги посчитаны
    route_notifications = [n for n in sender.sent if n.category is NotificationCategory.ROUTE]
    assert len(route_notifications) == 1
    notification = route_notifications[0]
    body = notification.body
    assert notification.title == "🧪 Демо-рекомендация"
    assert "DEMO · данные не из live ATI" in body
    assert "Москва → Санкт-Петербург" in body and "Чистая прибыль" in body
    assert notification.actions[0].label == "Открыть поиск ATI"
    assert notification.actions[0].url == "https://loads.ati.su/"
    assert notification.trace_id == "t-full"

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
