"""OSRM fallback route provider."""

from __future__ import annotations

from app.core.errors import GeocodingError
from app.core.models.routes import RouteEstimate, RouteRequest
from app.core.ports import GeocodingProvider
from app.infrastructure.routes.osrm.client import OsrmRoutesClient
from app.infrastructure.routes.osrm.mapper import map_osrm_route


class OsrmRouteProvider:
    """RouteProvider adapter for OSRM driving profile."""

    provider_id = "osrm"

    def __init__(self, *, client: OsrmRoutesClient, geocoder: GeocodingProvider) -> None:
        self._client = client
        self._geocoder = geocoder

    async def calculate_route(
        self,
        origin: str,
        destination: str,
        *,
        request: RouteRequest | None = None,
    ) -> RouteEstimate | None:
        """Calculate approximate car route via OSRM."""
        route_request = request if request is not None else RouteRequest.simple(origin, destination)
        origin_point = route_request.origin_point or await self._geocoder.geocode(origin)
        destination_point = route_request.destination_point or await self._geocoder.geocode(
            destination
        )
        if origin_point is None or destination_point is None:
            raise GeocodingError("OSRM route requires geocoded origin and destination")
        payload = await self._client.route(
            origin_point,
            destination_point,
            alternatives=route_request.alternatives,
        )
        return map_osrm_route(payload)
