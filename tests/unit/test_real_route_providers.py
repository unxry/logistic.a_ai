"""Stage 10.0: production route providers (Yandex + OSRM fallback)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.buses import EventBus
from app.core.errors import (
    GeocodingError,
    RouteAuthenticationError,
    RouteNetworkError,
    RouteNotFoundError,
    RouteProviderUnavailableError,
    RouteRateLimitError,
)
from app.core.events import (
    RouteCacheHit,
    RouteCacheMiss,
    RouteFallbackUsed,
    RouteProviderSelected,
)
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.matching import MatchingContext
from app.core.models.routes import (
    GeoPoint,
    RouteCachePolicy,
    RouteEstimate,
    RouteProviderChoice,
    RouteRequest,
    RouteVehicleParameters,
)
from app.infrastructure.routes import (
    CachedGeocodingProvider,
    CompositeRouteProvider,
    MockRouteProvider,
    OsrmRouteProvider,
    OsrmRoutesClient,
    StaticGeocodingProvider,
    YandexGeocodingProvider,
    YandexRoutesClient,
    YandexTruckRouteProvider,
)
from app.infrastructure.routes.osrm.mapper import map_osrm_route
from app.infrastructure.routes.yandex.mapper import map_yandex_route
from app.infrastructure.storage import Database, SqliteRouteCacheRepository
from app.services.matching import CargoProfitCalculator, RouteScoreCalculator
from app.services.routes import RouteCostCalculator, RouteService


def _point(lat: str = "55.755864", lon: str = "37.617698") -> GeoPoint:
    return GeoPoint(latitude=Decimal(lat), longitude=Decimal(lon), normalized_name="point")


def _vehicle() -> VehicleProfile:
    return VehicleProfile.create(
        name="12t truck",
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
        axle_weight_kg=8_000,
        vehicle_permits=("moscow_cargo_frame",),
    )


def _request(**overrides: Any) -> RouteRequest:
    vehicle = RouteVehicleParameters.from_profile(_vehicle())
    params: dict[str, Any] = {
        "origin": "Москва",
        "destination": "Казань",
        "origin_point": _point(),
        "destination_point": _point("55.796127", "49.106414"),
        "vehicle": vehicle,
        "avoid_tolls": True,
        "avoid_unpaved": True,
        "alternatives": 2,
        "traffic_enabled": True,
    }
    params.update(overrides)
    return RouteRequest(**params)


def _yandex_payload(
    *,
    distance: int = 726_000,
    duration: int = 36_720,
    tolls: bool = True,
    traffic_type: str = "forecast",
) -> dict[str, object]:
    return {
        "traffic_type": traffic_type,
        "route": {
            "legs": [
                {
                    "status": "OK",
                    "steps": [
                        {
                            "length": distance,
                            "duration": duration,
                            "polyline": {
                                "points": [
                                    [55.755864, 37.617698],
                                    [55.796127, 49.106414],
                                ]
                            },
                        }
                    ],
                }
            ],
            "flags": {"hasTolls": tolls},
        },
    }


def _osrm_payload(distance: float = 726_000.0, duration: float = 36_720.0) -> dict[str, object]:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": distance,
                "duration": duration,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[37.617698, 55.755864], [49.106414, 55.796127]],
                },
            }
        ],
    }


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "routes.db")
    database.connect()
    return database


class _FixedRouteProvider:
    provider_id = "fixed"

    def __init__(self, estimate: RouteEstimate | None, *, fail: Exception | None = None) -> None:
        self.estimate = estimate
        self.fail = fail
        self.calls = 0

    async def calculate_route(
        self,
        origin: str,
        destination: str,
        *,
        request: RouteRequest | None = None,
    ) -> RouteEstimate | None:
        self.calls += 1
        await asyncio.sleep(0)
        if self.fail is not None:
            raise self.fail
        return self.estimate


async def test_yandex_client_success_uses_truck_mode() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_yandex_payload())

    client = YandexRoutesClient(api_key_provider=lambda: "secret", client=_client(handler))
    payload = await client.route(_request())
    assert payload is not None
    assert seen["mode"] == "truck"
    assert seen["waypoints"] == "55.755864,37.617698|55.796127,49.106414"


async def test_yandex_client_sends_vehicle_weight_and_dimensions() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_yandex_payload())

    client = YandexRoutesClient(api_key_provider=lambda: "secret", client=_client(handler))
    await client.route(_request())
    assert seen["weight"] == "18"
    assert seen["max_weight"] == "18"
    assert seen["payload"] == "12"
    assert seen["height"] == "3.8"
    assert seen["width"] == "2.5"
    assert seen["length"] == "8.2"


async def test_yandex_client_sends_axle_weight_and_permits() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_yandex_payload())

    client = YandexRoutesClient(api_key_provider=lambda: "secret", client=_client(handler))
    await client.route(_request())
    assert seen["axle_weight"] == "8"
    assert seen["vehicle_permits"] == "moscow_cargo_frame"


async def test_yandex_client_sends_avoid_flags_and_alternatives() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_yandex_payload())

    client = YandexRoutesClient(api_key_provider=lambda: "secret", client=_client(handler))
    await client.route(_request())
    assert seen["avoid_tolls"] == "true"
    assert seen["avoid_unpaved"] == "true"
    assert seen["results"] == "2"


async def test_yandex_client_returns_none_without_key() -> None:
    client = YandexRoutesClient(
        api_key_provider=lambda: None, client=_client(lambda _: httpx.Response(500))
    )
    assert await client.route(_request()) is None


async def test_yandex_mapper_maps_distance_duration_tolls_polyline() -> None:
    estimate = map_yandex_route(_yandex_payload())
    assert estimate.distance_km == 726
    assert estimate.duration_hours == pytest.approx(10.2)
    assert estimate.has_tolls is True
    assert len(estimate.polyline) == 2


async def test_yandex_mapper_marks_traffic_aware() -> None:
    estimate = map_yandex_route(_yandex_payload(traffic_type="forecast"))
    assert estimate.traffic_aware is True
    assert estimate.traffic_duration_hours == pytest.approx(10.2)


async def test_yandex_mapper_rejects_empty_route() -> None:
    with pytest.raises(RouteNotFoundError):
        map_yandex_route(_yandex_payload(distance=0))


@pytest.mark.parametrize("status", [401, 403])
async def test_yandex_auth_errors_are_mapped(status: int) -> None:
    client = YandexRoutesClient(
        api_key_provider=lambda: "secret",
        client=_client(lambda _: httpx.Response(status, json={"message": "auth"})),
    )
    with pytest.raises(RouteAuthenticationError):
        await client.route(_request())


async def test_yandex_rate_limit_respects_retry_after() -> None:
    client = YandexRoutesClient(
        api_key_provider=lambda: "secret",
        client=_client(lambda _: httpx.Response(429, headers={"Retry-After": "7"})),
    )
    with pytest.raises(RouteRateLimitError) as exc_info:
        await client.route(_request())
    assert exc_info.value.retry_after == 7


async def test_yandex_5xx_is_provider_unavailable() -> None:
    client = YandexRoutesClient(
        api_key_provider=lambda: "secret",
        client=_client(lambda _: httpx.Response(500)),
    )
    with pytest.raises(RouteProviderUnavailableError):
        await client.route(_request())


async def test_yandex_timeout_is_network_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    client = YandexRoutesClient(api_key_provider=lambda: "secret", client=_client(handler))
    with pytest.raises(RouteNetworkError):
        await client.route(_request())


async def test_yandex_provider_geocodes_and_maps() -> None:
    provider = YandexTruckRouteProvider(
        client=YandexRoutesClient(
            api_key_provider=lambda: "secret",
            client=_client(lambda _: httpx.Response(200, json=_yandex_payload())),
        ),
        geocoder=StaticGeocodingProvider(),
    )
    estimate = await provider.calculate_route("Москва", "Казань")
    assert estimate is not None
    assert estimate.provider == "yandex"
    assert estimate.supports_truck_restrictions is True


async def test_yandex_provider_requires_geocoding() -> None:
    provider = YandexTruckRouteProvider(
        client=YandexRoutesClient(api_key_provider=lambda: "secret"),
        geocoder=StaticGeocodingProvider(points={}),
    )
    with pytest.raises(GeocodingError):
        await provider.calculate_route("Город A", "Город B")


async def test_osrm_client_success_uses_lon_lat_order() -> None:
    seen = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request.url.path
        return httpx.Response(200, json=_osrm_payload())

    client = OsrmRoutesClient(base_url="https://osrm.test", client=_client(handler))
    payload = await client.route(_point(), _point("55.796127", "49.106414"))
    assert payload["code"] == "Ok"
    assert "37.617698,55.755864;49.106414,55.796127" in seen


async def test_osrm_mapper_marks_approximate_capabilities() -> None:
    estimate = map_osrm_route(_osrm_payload())
    assert estimate.provider == "osrm"
    assert estimate.supports_truck_restrictions is False
    assert estimate.traffic_aware is False
    assert estimate.toll_information_available is False
    assert estimate.confidence_score < 80


async def test_osrm_no_route_raises_not_found() -> None:
    client = OsrmRoutesClient(
        base_url="https://osrm.test",
        client=_client(lambda _: httpx.Response(200, json={"code": "NoRoute"})),
    )
    with pytest.raises(RouteNotFoundError):
        await client.route(_point(), _point("55.796127", "49.106414"))


async def test_osrm_5xx_raises_unavailable() -> None:
    client = OsrmRoutesClient(
        base_url="https://osrm.test",
        client=_client(lambda _: httpx.Response(503)),
    )
    with pytest.raises(RouteProviderUnavailableError):
        await client.route(_point(), _point("55.796127", "49.106414"))


async def test_osrm_provider_uses_static_geocoding() -> None:
    provider = OsrmRouteProvider(
        client=OsrmRoutesClient(
            base_url="https://osrm.test",
            client=_client(lambda _: httpx.Response(200, json=_osrm_payload())),
        ),
        geocoder=StaticGeocodingProvider(),
    )
    estimate = await provider.calculate_route("Москва", "Казань")
    assert estimate is not None
    assert estimate.provider == "osrm"


async def test_static_geocoder_returns_known_city() -> None:
    point = await StaticGeocodingProvider().geocode("Москва")
    assert point is not None
    assert point.normalized_name == "Москва"


async def test_yandex_geocoder_maps_response() -> None:
    payload = {
        "response": {
            "GeoObjectCollection": {
                "featureMember": [
                    {
                        "GeoObject": {
                            "name": "Москва",
                            "Point": {"pos": "37.617698 55.755864"},
                        }
                    }
                ]
            }
        }
    }
    provider = YandexGeocodingProvider(
        api_key_provider=lambda: "secret",
        client=_client(lambda _: httpx.Response(200, json=payload)),
    )
    point = await provider.geocode("Москва")
    assert point is not None
    assert point.latitude == Decimal("55.755864")
    assert point.longitude == Decimal("37.617698")


async def test_cached_geocoder_hits_sqlite_cache(tmp_path: Path) -> None:
    database = _db(tmp_path)
    cache = SqliteRouteCacheRepository(database)
    inner = StaticGeocodingProvider()
    provider = CachedGeocodingProvider(inner=inner, cache=cache, policy=RouteCachePolicy())
    first = await provider.geocode("Москва")
    second = await CachedGeocodingProvider(
        inner=StaticGeocodingProvider(points={}),
        cache=cache,
        policy=RouteCachePolicy(),
    ).geocode("Москва")
    assert first == second
    database.close()


async def test_route_cache_hit_and_miss(tmp_path: Path) -> None:
    database = _db(tmp_path)
    cache = SqliteRouteCacheRepository(database)
    key = cache.route_key(_request(), provider="yandex")
    assert await cache.get_route(key, now=_request().origin_point.confidence and _now()) is None
    await cache.save_route(key, map_yandex_route(_yandex_payload()), ttl=timedelta(minutes=45))
    assert await cache.get_route(key, now=_now()) is not None
    database.close()


async def test_route_cache_ttl_expires_but_stale_remains(tmp_path: Path) -> None:
    database = _db(tmp_path)
    cache = SqliteRouteCacheRepository(database)
    key = cache.route_key(_request(), provider="yandex")
    await cache.save_route(key, map_yandex_route(_yandex_payload()), ttl=timedelta(seconds=-1))
    assert await cache.get_route(key, now=_now()) is None
    assert await cache.get_stale_route(key) is not None
    database.close()


async def test_route_cache_key_changes_with_vehicle_weight(tmp_path: Path) -> None:
    database = _db(tmp_path)
    cache = SqliteRouteCacheRepository(database)
    first = cache.route_key(_request(), provider="yandex")
    vehicle = RouteVehicleParameters(actual_weight_tons=Decimal("12"))
    second = cache.route_key(_request(vehicle=vehicle), provider="yandex")
    assert first != second
    database.close()


async def test_composite_yandex_success_returns_yandex(tmp_path: Path) -> None:
    provider = _composite(tmp_path, yandex=_FixedRouteProvider(map_yandex_route(_yandex_payload())))
    estimate = await provider.calculate_route("Москва", "Казань", request=_request())
    assert estimate is not None
    assert estimate.provider == "yandex"
    assert estimate.is_fallback is False


async def test_composite_yandex_to_osrm_fallback(tmp_path: Path) -> None:
    provider = _composite(
        tmp_path,
        yandex=_FixedRouteProvider(None, fail=RouteProviderUnavailableError("down")),
        osrm=_FixedRouteProvider(map_osrm_route(_osrm_payload())),
    )
    estimate = await provider.calculate_route("Москва", "Казань", request=_request())
    assert estimate is not None
    assert estimate.provider == "osrm"
    assert estimate.is_fallback is True
    assert "Маршрут рассчитан без учёта ограничений грузовика" in estimate.warnings


async def test_composite_osrm_to_stale_cache_fallback(tmp_path: Path) -> None:
    database = _db(tmp_path)
    cache = SqliteRouteCacheRepository(database)
    request = _request()
    key = cache.route_key(request, provider="osrm")
    await cache.save_route(key, map_osrm_route(_osrm_payload()), ttl=timedelta(seconds=-1))
    provider = CompositeRouteProvider(
        yandex=_FixedRouteProvider(None),
        osrm=_FixedRouteProvider(None, fail=RouteProviderUnavailableError("down")),
        mock=None,
        geocoder=StaticGeocodingProvider(),
        cache=cache,
        provider_choice=RouteProviderChoice.OSRM,
    )
    estimate = await provider.calculate_route("Москва", "Казань", request=request)
    assert estimate is not None
    assert "Использован устаревший кэш маршрута" in estimate.warnings
    database.close()


async def test_composite_cache_prevents_second_provider_call(tmp_path: Path) -> None:
    yandex = _FixedRouteProvider(map_yandex_route(_yandex_payload()))
    provider = _composite(tmp_path, yandex=yandex)
    await provider.calculate_route("Москва", "Казань", request=_request())
    await provider.calculate_route("Москва", "Казань", request=_request())
    assert yandex.calls == 1


async def test_composite_concurrent_identical_requests_share_one_call(tmp_path: Path) -> None:
    yandex = _FixedRouteProvider(map_yandex_route(_yandex_payload()))
    provider = _composite(tmp_path, yandex=yandex)
    results = await asyncio.gather(
        provider.calculate_route("Москва", "Казань", request=_request()),
        provider.calculate_route("Москва", "Казань", request=_request()),
        provider.calculate_route("Москва", "Казань", request=_request()),
    )
    assert all(result is not None for result in results)
    assert yandex.calls == 1


async def test_composite_publishes_provider_cache_and_fallback_events(tmp_path: Path) -> None:
    bus = EventBus()
    selected: list[RouteProviderSelected] = []
    misses: list[RouteCacheMiss] = []
    hits: list[RouteCacheHit] = []
    fallbacks: list[RouteFallbackUsed] = []
    bus.subscribe(RouteProviderSelected, selected.append)
    bus.subscribe(RouteCacheMiss, misses.append)
    bus.subscribe(RouteCacheHit, hits.append)
    bus.subscribe(RouteFallbackUsed, fallbacks.append)
    provider = _composite(
        tmp_path,
        yandex=_FixedRouteProvider(None, fail=RouteProviderUnavailableError("down")),
        osrm=_FixedRouteProvider(map_osrm_route(_osrm_payload())),
        events=bus,
    )
    await provider.calculate_route("Москва", "Казань", request=_request())
    await provider.calculate_route("Москва", "Казань", request=_request())
    assert selected
    assert misses
    assert hits
    assert fallbacks[0].from_provider == "yandex"
    assert fallbacks[0].to_provider == "osrm"


async def test_route_service_enriches_real_estimate_and_profit() -> None:
    estimate = map_yandex_route(_yandex_payload())
    service = RouteService(
        provider=_FixedRouteProvider(estimate),
        costs=RouteCostCalculator(),
        event_bus=EventBus(),
    )
    cargo = _cargo()
    enriched = await service.estimate_for_cargo(cargo, vehicle_profile=_vehicle())
    analysis = CargoProfitCalculator().analyze(cargo, enriched)
    assert enriched is not None
    assert enriched.total_cost > 0
    assert analysis is not None
    assert analysis.net_profit < cargo.payment_amount


async def test_low_confidence_route_slightly_reduces_route_score() -> None:
    cargo = _cargo()
    driver = DriverProfile.create(home_region="Тверь")
    precise = MatchingContext(_vehicle(), driver, "Пермь", map_yandex_route(_yandex_payload()))
    rough = MatchingContext(
        _vehicle(),
        driver,
        "Пермь",
        RouteEstimate(distance_km=726, duration_hours=10, confidence_score=40),
    )
    calculator = RouteScoreCalculator()
    precise_score, _ = calculator.score(cargo, precise)
    rough_score, rough_notes = calculator.score(cargo, rough)
    assert precise_score > rough_score
    assert "Маршрут оценён приблизительно" in rough_notes


async def test_osrm_explanation_warns_about_truck_restrictions() -> None:
    cargo = _cargo()
    driver = DriverProfile.create(home_region="Москва")
    context = MatchingContext(_vehicle(), driver, "Москва", map_osrm_route(_osrm_payload()))
    _score, notes = RouteScoreCalculator().score(cargo, context)
    assert "OSRM" in " ".join(notes)
    assert "ограничений грузовика" in " ".join(notes)


async def test_secret_is_not_in_yandex_error_text() -> None:
    client = YandexRoutesClient(
        api_key_provider=lambda: "super-secret-key",
        client=_client(lambda _: httpx.Response(401, json={"message": "bad key"})),
    )
    with pytest.raises(RouteAuthenticationError) as exc_info:
        await client.route(_request())
    assert "super-secret-key" not in str(exc_info.value)


def _now() -> Any:
    from app.core.clock import utc_now

    return utc_now()


def _cargo() -> Cargo:
    return Cargo(
        id="cargo-route-test",
        source_id="ati",
        title="Москва → Казань",
        loading_region="Москва",
        unloading_region="Казань",
        payment_amount=Decimal("120000"),
        distance_km=726,
        weight_kg=8_000,
        volume_m3=40.0,
    )


def _composite(
    tmp_path: Path,
    *,
    yandex: _FixedRouteProvider | None = None,
    osrm: _FixedRouteProvider | None = None,
    events: EventBus | None = None,
) -> CompositeRouteProvider:
    database = _db(tmp_path)
    return CompositeRouteProvider(
        yandex=yandex,
        osrm=osrm,
        mock=MockRouteProvider(),
        geocoder=StaticGeocodingProvider(),
        cache=SqliteRouteCacheRepository(database),
        events=events,
        provider_choice=RouteProviderChoice.AUTO,
    )
