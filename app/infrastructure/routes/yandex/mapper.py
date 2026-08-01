"""Map Yandex Router response to RouteEstimate."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

from app.core.errors import RouteNotFoundError, RouteProviderUnavailableError
from app.core.models.routes import GeoPoint, RouteEstimate


def map_yandex_route(payload: Mapping[str, Any]) -> RouteEstimate:
    """Yandex JSON → RouteEstimate."""
    route = _select_route(payload)
    legs = route.get("legs", ())
    distance_m = 0.0
    duration_s = 0.0
    polyline: list[GeoPoint] = []
    warnings: list[str] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            continue
        if leg.get("status") not in (None, "OK"):
            warnings.append(f"Yandex leg status: {leg.get('status')}")
        for step in leg.get("steps", ()):
            if not isinstance(step, Mapping):
                continue
            distance_m += float(step.get("length", 0.0))
            duration_s += float(step.get("duration", 0.0))
            points = (
                step.get("polyline", {}).get("points", ())
                if isinstance(step.get("polyline"), Mapping)
                else ()
            )
            for item in points:
                if isinstance(item, list | tuple) and len(item) >= 2:
                    polyline.append(
                        GeoPoint(
                            latitude=Decimal(str(item[0])),
                            longitude=Decimal(str(item[1])),
                            confidence=90,
                        )
                    )
    if distance_m <= 0:
        raise RouteNotFoundError("Yandex Routes returned empty route")
    flags = route.get("flags", {}) if isinstance(route.get("flags"), Mapping) else {}
    has_tolls = bool(flags.get("hasTolls", False))
    traffic_type = str(payload.get("traffic_type", ""))
    return RouteEstimate(
        distance_km=distance_m / 1000,
        duration_hours=duration_s / 3600,
        confidence_score=95,
        provider="yandex",
        provider_label="Яндекс, грузовой маршрут",
        warnings=tuple(warnings),
        traffic_duration_hours=duration_s / 3600 if traffic_type != "disabled" else None,
        has_tolls=has_tolls,
        polyline=tuple(polyline),
        supports_truck_restrictions=True,
        traffic_aware=traffic_type in ("realtime", "forecast"),
        toll_information_available=True,
        metadata={"traffic_type": traffic_type},
    )


def _select_route(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload.get("route"), Mapping):
        return cast("Mapping[str, Any]", payload["route"])
    routes = payload.get("routes")
    if isinstance(routes, list) and routes and isinstance(routes[0], Mapping):
        return cast("Mapping[str, Any]", routes[0])
    errors = payload.get("errors")
    if errors:
        raise RouteProviderUnavailableError("; ".join(str(item) for item in errors))
    raise RouteNotFoundError("Yandex Routes response has no route")
