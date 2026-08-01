"""Yandex truck route provider."""

from __future__ import annotations

from app.core.errors import GeocodingError
from app.core.models.routes import RouteEstimate, RouteRequest
from app.core.ports import GeocodingProvider
from app.infrastructure.routes.yandex.client import YandexRoutesClient
from app.infrastructure.routes.yandex.mapper import map_yandex_route


class YandexTruckRouteProvider:
    """RouteProvider adapter for Yandex truck routing."""

    provider_id = "yandex"

    def __init__(self, *, client: YandexRoutesClient, geocoder: GeocodingProvider) -> None:
        self._client = client
        self._geocoder = geocoder

    async def calculate_route(
        self,
        origin: str,
        destination: str,
        *,
        request: RouteRequest | None = None,
    ) -> RouteEstimate | None:
        """Calculate truck route via Yandex."""
        route_request = request if request is not None else RouteRequest.simple(origin, destination)
        origin_point = route_request.origin_point or await self._geocoder.geocode(origin)
        destination_point = route_request.destination_point or await self._geocoder.geocode(
            destination
        )
        if origin_point is None or destination_point is None:
            raise GeocodingError("Yandex route requires geocoded origin and destination")
        route_request = RouteRequest(
            origin=route_request.origin,
            destination=route_request.destination,
            origin_point=origin_point,
            destination_point=destination_point,
            vehicle=route_request.vehicle,
            departure_at=route_request.departure_at,
            avoid_tolls=route_request.avoid_tolls,
            avoid_unpaved=route_request.avoid_unpaved,
            alternatives=route_request.alternatives,
            traffic_enabled=route_request.traffic_enabled,
        )
        payload = await self._client.route(route_request)
        if payload is None:
            return None
        return map_yandex_route(payload)
