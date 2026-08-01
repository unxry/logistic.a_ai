"""Live Yandex Truck Routing smoke.

Run manually:
    YANDEX_ROUTER_API_KEY="..." uv run python scripts/yandex_routes_smoke.py

The key is read from env only and is never printed.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.routes import RouteRequest, RouteVehicleParameters
from app.infrastructure.routes import (
    StaticGeocodingProvider,
    YandexRoutesClient,
    YandexTruckRouteProvider,
)
from app.services.matching import CargoProfitCalculator
from app.services.routes import RouteCostCalculator


async def main() -> int:
    """Call Yandex Router API once and print a safe smoke report."""
    api_key = os.environ.get("YANDEX_ROUTER_API_KEY")
    if not api_key:
        print("YANDEX_ROUTER_API_KEY is not set")
        return 2

    vehicle = VehicleProfile.create(
        name="12t smoke truck",
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
    request = RouteRequest(
        origin="Москва",
        destination="Казань",
        origin_point=await StaticGeocodingProvider().geocode("Москва"),
        destination_point=await StaticGeocodingProvider().geocode("Казань"),
        vehicle=RouteVehicleParameters.from_profile(vehicle),
        traffic_enabled=True,
        alternatives=1,
    )
    provider = YandexTruckRouteProvider(
        client=YandexRoutesClient(api_key_provider=lambda: api_key),
        geocoder=StaticGeocodingProvider(),
    )
    estimate = await provider.calculate_route("Москва", "Казань", request=request)
    if estimate is None:
        print("Yandex truck route: no result")
        return 1

    enriched = RouteCostCalculator().enrich(estimate)
    cargo = Cargo(
        id="smoke-yandex-route",
        source_id="smoke",
        title="Москва → Казань",
        loading_region="Москва",
        unloading_region="Казань",
        payment_amount=Decimal("120000"),
        distance_km=enriched.distance_km,
    )
    analysis = CargoProfitCalculator().analyze(cargo, enriched)
    if analysis is None:
        print("Net profit recalculation failed")
        return 1
    print("Yandex truck route: live success")
    print(f"Distance: {enriched.distance_km:.0f} km")
    print(f"Duration: {enriched.duration_hours:.2f} h")
    print(f"Tolls: {'yes' if enriched.has_tolls else 'no'}")
    print(f"Confidence: {enriched.confidence_score}")
    print(f"Net profit recalculated: {analysis.net_profit} ₽")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
