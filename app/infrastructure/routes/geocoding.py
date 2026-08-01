"""Geocoding providers: static, cached and Yandex HTTP."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import httpx

from app.core.clock import utc_now
from app.core.errors import GeocodingError, RouteAuthenticationError, RouteRateLimitError
from app.core.models.routes import GeoPoint, RouteCachePolicy
from app.core.ports import GeocodingProvider, RouteCacheRepository

_YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"

_DEFAULT_POINTS: dict[str, GeoPoint] = {
    "москва": GeoPoint(Decimal("55.755864"), Decimal("37.617698"), "Москва", 95),
    "санкт-петербург": GeoPoint(
        Decimal("59.938784"),
        Decimal("30.314997"),
        "Санкт-Петербург",
        95,
    ),
    "казань": GeoPoint(Decimal("55.796127"), Decimal("49.106414"), "Казань", 95),
    "екатеринбург": GeoPoint(Decimal("56.838011"), Decimal("60.597465"), "Екатеринбург", 95),
    "нижний новгород": GeoPoint(Decimal("56.326797"), Decimal("44.006516"), "Нижний Новгород", 95),
    "воронеж": GeoPoint(Decimal("51.660781"), Decimal("39.200296"), "Воронеж", 95),
    "тверь": GeoPoint(Decimal("56.858721"), Decimal("35.917600"), "Тверь", 95),
    "пермь": GeoPoint(Decimal("58.010455"), Decimal("56.229443"), "Пермь", 90),
    "сургут": GeoPoint(Decimal("61.254035"), Decimal("73.396221"), "Сургут", 90),
}


class StaticGeocodingProvider:
    """Статический геокодер для тестов/offline fallback."""

    def __init__(self, points: Mapping[str, GeoPoint] | None = None) -> None:
        self._points = dict(points) if points is not None else dict(_DEFAULT_POINTS)

    async def geocode(self, location: str) -> GeoPoint | None:
        """Вернуть координаты из таблицы."""
        return self._points.get(location.strip().casefold())


class CachedGeocodingProvider:
    """Кэш-обёртка над любым GeocodingProvider."""

    def __init__(
        self,
        *,
        inner: GeocodingProvider,
        cache: RouteCacheRepository,
        policy: RouteCachePolicy | None = None,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._policy = policy if policy is not None else RouteCachePolicy()

    async def geocode(self, location: str) -> GeoPoint | None:
        """Cache hit → inner → save."""
        now = utc_now()
        cached = await self._cache.get_geocode(location, now=now)
        if cached is not None:
            return cached
        point = await self._inner.geocode(location)
        if point is not None:
            await self._cache.save_geocode(location, point, ttl=self._policy.geocoding_ttl)
        return point


class FallbackGeocodingProvider:
    """Пробует несколько геокодеров по порядку."""

    def __init__(self, providers: tuple[GeocodingProvider, ...]) -> None:
        self._providers = providers

    async def geocode(self, location: str) -> GeoPoint | None:
        """Первый успешный геокод."""
        for provider in self._providers:
            point = await provider.geocode(location)
            if point is not None:
                return point
        return None


class YandexGeocodingProvider:
    """Yandex Geocoder API adapter."""

    def __init__(
        self,
        *,
        api_key_provider: Callable[[], str | None],
        client: httpx.AsyncClient | None = None,
        base_url: str = _YANDEX_GEOCODER_URL,
    ) -> None:
        self._api_key_provider = api_key_provider
        self._client = client
        self._base_url = base_url

    async def geocode(self, location: str) -> GeoPoint | None:
        """Геокодировать строку через Yandex."""
        key = self._api_key()
        if not key:
            return None
        close_client = self._client is None
        client = self._client if self._client is not None else httpx.AsyncClient(timeout=10)
        try:
            response = await client.get(
                self._base_url,
                params={"apikey": key, "geocode": location, "format": "json", "results": "1"},
            )
        except httpx.HTTPError as exc:
            raise GeocodingError("Yandex geocoder network error") from exc
        finally:
            if close_client:
                await client.aclose()
        if response.status_code in (401, 403):
            raise RouteAuthenticationError("Yandex geocoder rejected credentials")
        if response.status_code == 429:
            raise RouteRateLimitError("Yandex geocoder rate limit")
        if response.status_code >= 500:
            raise GeocodingError("Yandex geocoder unavailable")
        if response.status_code != 200:
            return None
        return _map_yandex_geocode(response.json())

    def _api_key(self) -> str:
        value = self._api_key_provider()
        return str(value) if value is not None else ""


def _map_yandex_geocode(payload: Mapping[str, Any]) -> GeoPoint | None:
    try:
        collection = payload["response"]["GeoObjectCollection"]
        members = collection["featureMember"]
        if not members:
            return None
        geo_object = members[0]["GeoObject"]
        lon_raw, lat_raw = str(geo_object["Point"]["pos"]).split()
        name = str(geo_object.get("name", ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("Yandex geocoder response is malformed") from exc
    return GeoPoint(
        latitude=Decimal(lat_raw),
        longitude=Decimal(lon_raw),
        normalized_name=name,
        confidence=90 if name else 70,
    )
