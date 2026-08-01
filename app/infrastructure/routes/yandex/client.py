"""HTTP client for Yandex Retrieving Route Details API."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.core.errors import RouteNetworkError
from app.core.models.routes import RouteRequest
from app.infrastructure.routes.yandex.errors import map_yandex_error

_BASE_URL = "https://api.routing.yandex.net/v2/route"


class YandexRoutesClient:
    """Thin HTTP client; response mapping lives in mapper.py."""

    def __init__(
        self,
        *,
        api_key_provider: Callable[[], str | None],
        client: httpx.AsyncClient | None = None,
        base_url: str = _BASE_URL,
    ) -> None:
        self._api_key_provider = api_key_provider
        self._client = client
        self._base_url = base_url

    async def route(self, request: RouteRequest) -> dict[str, object] | None:
        """GET /v2/route; None means API key not configured."""
        key = self._api_key_provider()
        if not key:
            return None
        params = _params(request, key)
        close_client = self._client is None
        client = self._client if self._client is not None else httpx.AsyncClient(timeout=12)
        try:
            response = await client.get(self._base_url, params=params)
        except httpx.TimeoutException as exc:
            raise RouteNetworkError("Yandex Routes timeout") from exc
        except httpx.HTTPError as exc:
            raise RouteNetworkError("Yandex Routes network error") from exc
        finally:
            if close_client:
                await client.aclose()
        if response.status_code != 200:
            raise map_yandex_error(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RouteNetworkError("Yandex Routes malformed JSON")
        return payload


def _params(request: RouteRequest, api_key: str) -> dict[str, str]:
    if request.origin_point is None or request.destination_point is None:
        raise RouteNetworkError("Yandex Routes request has no coordinates")
    params = {
        "apikey": api_key,
        "waypoints": f"{request.origin_point.yandex_pair}|{request.destination_point.yandex_pair}",
        "mode": "truck",
        "avoid_tolls": _bool(request.avoid_tolls),
        "avoid_unpaved": _bool(request.avoid_unpaved),
        "results": str(max(1, min(3, request.alternatives))),
    }
    if request.departure_at is not None:
        params["departure_time"] = str(int(request.departure_at.timestamp()))
    if not request.traffic_enabled:
        params["traffic"] = "disabled"
    vehicle = request.vehicle
    if vehicle is not None:
        _decimal_param(params, "weight", vehicle.actual_weight_tons)
        _decimal_param(params, "axle_weight", vehicle.axle_weight_tons)
        _decimal_param(params, "max_weight", vehicle.max_weight_tons)
        _decimal_param(params, "height", vehicle.height_m)
        _decimal_param(params, "width", vehicle.width_m)
        _decimal_param(params, "length", vehicle.length_m)
        _decimal_param(params, "payload", vehicle.payload_tons)
        if vehicle.vehicle_permits:
            params["vehicle_permits"] = ",".join(vehicle.vehicle_permits)
        if vehicle.has_trailer:
            params["has_trailer"] = "true"
        if vehicle.eco_class is not None:
            params["eco_class"] = str(vehicle.eco_class)
    return params


def _decimal_param(params: dict[str, str], key: str, value: object | None) -> None:
    if value is not None:
        params[key] = str(value)


def _bool(value: bool) -> str:
    return "true" if value else "false"
