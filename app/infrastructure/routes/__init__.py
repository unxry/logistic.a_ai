"""Адаптеры провайдеров маршрутов (порт RouteProvider)."""

from app.infrastructure.routes.composite import CompositeRouteProvider
from app.infrastructure.routes.geocoding import (
    CachedGeocodingProvider,
    FallbackGeocodingProvider,
    StaticGeocodingProvider,
    YandexGeocodingProvider,
)
from app.infrastructure.routes.mock import MockRouteProvider
from app.infrastructure.routes.osrm import OsrmRouteProvider, OsrmRoutesClient
from app.infrastructure.routes.yandex import YandexRoutesClient, YandexTruckRouteProvider

__all__ = [
    "CachedGeocodingProvider",
    "CompositeRouteProvider",
    "FallbackGeocodingProvider",
    "MockRouteProvider",
    "OsrmRouteProvider",
    "OsrmRoutesClient",
    "StaticGeocodingProvider",
    "YandexGeocodingProvider",
    "YandexRoutesClient",
    "YandexTruckRouteProvider",
]
