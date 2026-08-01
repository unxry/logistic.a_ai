"""Map OSRM response to RouteEstimate."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.core.errors import RouteNotFoundError
from app.core.models.routes import GeoPoint, RouteEstimate


def map_osrm_route(payload: Mapping[str, Any]) -> RouteEstimate:
    """OSRM JSON → approximate RouteEstimate."""
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RouteNotFoundError("OSRM response has no routes")
    route = routes[0]
    if not isinstance(route, Mapping):
        raise RouteNotFoundError("OSRM response route is malformed")
    distance_m = float(route.get("distance", 0.0))
    duration_s = float(route.get("duration", 0.0))
    if distance_m <= 0:
        raise RouteNotFoundError("OSRM returned empty route")
    polyline = _polyline(route.get("geometry"))
    return RouteEstimate(
        distance_km=distance_m / 1000,
        duration_hours=duration_s / 3600,
        confidence_score=68,
        provider="osrm",
        provider_label="OSRM, приблизительный маршрут",
        is_fallback=True,
        warnings=("Маршрут рассчитан без учёта ограничений грузовика",),
        has_tolls=None,
        polyline=polyline,
        supports_truck_restrictions=False,
        traffic_aware=False,
        toll_information_available=False,
        metadata={"alternatives": str(max(0, len(routes) - 1))},
    )


def _polyline(geometry: object) -> tuple[GeoPoint, ...]:
    if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
        return ()
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return ()
    points: list[GeoPoint] = []
    for item in coordinates:
        if isinstance(item, list | tuple) and len(item) >= 2:
            points.append(
                GeoPoint(
                    latitude=Decimal(str(item[1])),
                    longitude=Decimal(str(item[0])),
                    confidence=68,
                )
            )
    return tuple(points)
