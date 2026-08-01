"""Yandex Router specific error mapping."""

from __future__ import annotations

import httpx

from app.core.errors import (
    RouteAuthenticationError,
    RouteNetworkError,
    RouteNotFoundError,
    RouteProviderUnavailableError,
    RouteRateLimitError,
)


def map_yandex_error(response: httpx.Response) -> Exception:
    """HTTP status → domain route error."""
    if response.status_code in (401, 403):
        return RouteAuthenticationError("Yandex Routes rejected credentials")
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        try:
            retry = float(retry_after) if retry_after is not None else None
        except ValueError:
            retry = None
        return RouteRateLimitError("Yandex Routes rate limit", retry_after=retry)
    if response.status_code == 404:
        return RouteNotFoundError("Yandex Routes route not found")
    if response.status_code >= 500:
        return RouteProviderUnavailableError("Yandex Routes unavailable")
    return RouteNetworkError(f"Yandex Routes HTTP {response.status_code}")
