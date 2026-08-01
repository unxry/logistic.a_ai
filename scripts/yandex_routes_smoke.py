"""Live Yandex Truck Routing smoke using the production route chain."""

from __future__ import annotations

import asyncio
import os

from app.bootstrap import build_container
from app.container import AppContainer
from app.core.events import RouteCacheHit, RouteFallbackUsed
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.routes import RouteRequest, RouteVehicleParameters
from app.core.ports.secret_store import YANDEX_ROUTER_API_KEY_KEY
from app.infrastructure.settings.secret_store import KeyringSecretStore

ROUTES: tuple[tuple[str, str], ...] = (
    ("Москва", "Санкт-Петербург"),
    ("Москва", "Казань"),
    ("Москва", "Нижний Новгород"),
)


def _vehicle() -> VehicleProfile:
    return VehicleProfile.create(
        name="12t live truck",
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
    )


async def _close(container: AppContainer) -> None:
    await container.ati_client.aclose()
    await container.notification_service.aclose()
    container.database.close()


async def _run_once(container: AppContainer, origin: str, destination: str) -> None:
    request = RouteRequest(
        origin=origin,
        destination=destination,
        vehicle=RouteVehicleParameters.from_profile(_vehicle()),
        traffic_enabled=True,
        alternatives=1,
    )
    estimate = await container.route_service.estimate(
        origin,
        destination,
        trace_id="yandex-routes-smoke",
        request=request,
    )
    if estimate is None:
        print(f"{origin} → {destination}: no route")
        raise SystemExit(1)
    print(f"{origin} → {destination}")
    print(f"Provider: {estimate.provider_label}")
    print(f"Mode: {'truck' if estimate.supports_truck_restrictions else 'approximate'}")
    print(f"Distance: {estimate.distance_km:.0f} km")
    print(f"Duration: {estimate.duration_hours:.2f} h")
    tolls = "yes" if estimate.has_tolls else "no" if estimate.has_tolls is False else "unknown"
    print(f"Tolls: {tolls}")
    print(f"Truck restrictions supported: {estimate.supports_truck_restrictions}")
    print(f"Confidence: {estimate.confidence_score}")
    if estimate.is_fallback:
        print("Approximate route")
        print("Truck restrictions not included")
    print()


async def main() -> int:
    """Call Yandex through LogistAI production routing without printing the key."""
    store = KeyringSecretStore()
    env_key = os.environ.get("YANDEX_ROUTER_API_KEY")
    if env_key and not store.get(YANDEX_ROUTER_API_KEY_KEY):
        store.set(YANDEX_ROUTER_API_KEY_KEY, env_key)
    if not store.get(YANDEX_ROUTER_API_KEY_KEY):
        print("Yandex Router key is not stored in Keychain")
        return 2

    cache_hits = 0
    fallbacks = 0
    container = build_container()

    def on_cache(_: RouteCacheHit) -> None:
        nonlocal cache_hits
        cache_hits += 1

    def on_fallback(_: RouteFallbackUsed) -> None:
        nonlocal fallbacks
        fallbacks += 1

    container.event_bus.subscribe(RouteCacheHit, on_cache)
    container.event_bus.subscribe(RouteFallbackUsed, on_fallback)
    try:
        for origin, destination in ROUTES:
            await _run_once(container, origin, destination)
    finally:
        await _close(container)

    second = build_container()
    second.event_bus.subscribe(RouteCacheHit, on_cache)
    try:
        await _run_once(second, ROUTES[0][0], ROUTES[0][1])
    finally:
        await _close(second)

    print(f"cache_hit={cache_hits > 0}")
    print(f"fallbacks={fallbacks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
