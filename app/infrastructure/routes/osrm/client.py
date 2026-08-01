"""HTTP client for OSRM route service."""

from __future__ import annotations

import httpx

from app.core.errors import RouteNetworkError, RouteNotFoundError, RouteProviderUnavailableError
from app.core.models.routes import GeoPoint

_DEFAULT_BASE_URL = "https://router.project-osrm.org"


class OsrmRoutesClient:
    """Thin OSRM HTTP client."""

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        *,
        alternatives: int = 1,
    ) -> dict[str, object]:
        """GET /route/v1/driving/{lon,lat;lon,lat}."""
        coordinates = f"{origin.osrm_pair};{destination.osrm_pair}"
        url = f"{self._base_url}/route/v1/driving/{coordinates}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "alternatives": str(max(0, alternatives - 1)),
            "steps": "false",
        }
        close_client = self._client is None
        client = self._client if self._client is not None else httpx.AsyncClient(timeout=10)
        try:
            response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise RouteNetworkError("OSRM timeout") from exc
        except httpx.HTTPError as exc:
            raise RouteNetworkError("OSRM network error") from exc
        finally:
            if close_client:
                await client.aclose()
        if response.status_code >= 500:
            raise RouteProviderUnavailableError("OSRM unavailable")
        if response.status_code != 200:
            raise RouteNetworkError(f"OSRM HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RouteNetworkError("OSRM malformed JSON")
        if payload.get("code") == "NoRoute":
            raise RouteNotFoundError("OSRM route not found")
        return payload
