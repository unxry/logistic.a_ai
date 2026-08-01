"""SQLite route/geocoding cache для production route providers."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from app.core.clock import utc_now
from app.core.models.routes import GeoPoint, RouteEstimate, RouteRequest
from app.infrastructure.storage.database import Database


class SqliteRouteCacheRepository:
    """Persistent cache маршрутов и геокодинга."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get_route(self, key: str, *, now: datetime) -> RouteEstimate | None:
        """Маршрут из кэша, если не истёк TTL."""
        rows = await asyncio.to_thread(
            self._db.query,
            "SELECT estimate_json FROM route_cache WHERE cache_key = ? AND expires_at > ?",
            (key, now.isoformat()),
        )
        return _estimate_from_json(str(rows[0]["estimate_json"])) if rows else None

    async def get_stale_route(self, key: str) -> RouteEstimate | None:
        """Последний маршрут даже после TTL — только для аварийного fallback."""
        rows = await asyncio.to_thread(
            self._db.query,
            "SELECT estimate_json FROM route_cache WHERE cache_key = ?",
            (key,),
        )
        return _estimate_from_json(str(rows[0]["estimate_json"])) if rows else None

    async def save_route(self, key: str, estimate: RouteEstimate, *, ttl: timedelta) -> None:
        """Сохранить маршрут с TTL."""
        now = utc_now()
        await asyncio.to_thread(
            self._db.execute,
            """
            INSERT INTO route_cache (cache_key, provider, estimate_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                provider = excluded.provider,
                estimate_json = excluded.estimate_json,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (
                key,
                estimate.provider,
                _estimate_to_json(estimate),
                now.isoformat(),
                (now + ttl).isoformat(),
            ),
        )

    async def get_geocode(self, location: str, *, now: datetime) -> GeoPoint | None:
        """Геокод из кэша, если не истёк TTL."""
        rows = await asyncio.to_thread(
            self._db.query,
            """
            SELECT latitude, longitude, normalized_name, confidence
            FROM geocoding_cache
            WHERE location_key = ? AND expires_at > ?
            """,
            (_location_key(location), now.isoformat()),
        )
        if not rows:
            return None
        row = rows[0]
        return GeoPoint(
            latitude=Decimal(str(row["latitude"])),
            longitude=Decimal(str(row["longitude"])),
            normalized_name=str(row["normalized_name"]),
            confidence=int(row["confidence"]),
        )

    async def save_geocode(self, location: str, point: GeoPoint, *, ttl: timedelta) -> None:
        """Сохранить геокод с TTL."""
        now = utc_now()
        await asyncio.to_thread(
            self._db.execute,
            """
            INSERT INTO geocoding_cache (
                location_key,
                latitude,
                longitude,
                normalized_name,
                confidence,
                created_at,
                expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_key) DO UPDATE SET
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                normalized_name = excluded.normalized_name,
                confidence = excluded.confidence,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (
                _location_key(location),
                str(point.latitude),
                str(point.longitude),
                point.normalized_name,
                point.confidence,
                now.isoformat(),
                (now + ttl).isoformat(),
            ),
        )

    def route_key(self, request: RouteRequest, *, provider: str) -> str:
        """Стабильный ключ маршрута с учётом координат, грузовика и настроек."""
        vehicle = request.vehicle
        origin = request.origin_point.yandex_pair if request.origin_point else request.origin
        destination = (
            request.destination_point.yandex_pair
            if request.destination_point
            else request.destination
        )
        departure_bucket = ""
        if request.departure_at is not None:
            bucket = request.departure_at.replace(minute=0, second=0, microsecond=0)
            departure_bucket = bucket.isoformat()
        payload = {
            "provider": provider,
            "origin": origin,
            "destination": destination,
            "vehicle": {
                "actual": str(vehicle.actual_weight_tons) if vehicle else "",
                "max": str(vehicle.max_weight_tons) if vehicle else "",
                "payload": str(vehicle.payload_tons) if vehicle else "",
                "axle": str(vehicle.axle_weight_tons) if vehicle else "",
                "height": str(vehicle.height_m) if vehicle else "",
                "width": str(vehicle.width_m) if vehicle else "",
                "length": str(vehicle.length_m) if vehicle else "",
                "permits": vehicle.vehicle_permits if vehicle else (),
            },
            "avoid_tolls": request.avoid_tolls,
            "avoid_unpaved": request.avoid_unpaved,
            "departure_bucket": departure_bucket,
        }
        return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _location_key(location: str) -> str:
    return location.strip().casefold()


def _estimate_to_json(estimate: RouteEstimate) -> str:
    return json.dumps(
        {
            "distance_km": estimate.distance_km,
            "duration_hours": estimate.duration_hours,
            "confidence_score": estimate.confidence_score,
            "provider": estimate.provider,
            "provider_label": estimate.provider_label,
            "is_fallback": estimate.is_fallback,
            "warnings": list(estimate.warnings),
            "calculated_at": estimate.calculated_at.isoformat(),
            "traffic_duration_hours": estimate.traffic_duration_hours,
            "has_tolls": estimate.has_tolls,
            "polyline": [
                [str(point.latitude), str(point.longitude), point.normalized_name, point.confidence]
                for point in estimate.polyline
            ],
            "supports_truck_restrictions": estimate.supports_truck_restrictions,
            "traffic_aware": estimate.traffic_aware,
            "toll_information_available": estimate.toll_information_available,
            "metadata": dict(estimate.metadata),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _estimate_from_json(payload: str) -> RouteEstimate:
    data: dict[str, Any] = json.loads(payload)
    return RouteEstimate(
        distance_km=float(data["distance_km"]),
        duration_hours=float(data["duration_hours"]),
        confidence_score=int(data["confidence_score"]),
        provider=str(data["provider"]),
        provider_label=str(data["provider_label"]),
        is_fallback=bool(data["is_fallback"]),
        warnings=tuple(str(item) for item in data.get("warnings", ())),
        calculated_at=datetime.fromisoformat(str(data["calculated_at"])),
        traffic_duration_hours=(
            float(data["traffic_duration_hours"])
            if data.get("traffic_duration_hours") is not None
            else None
        ),
        has_tolls=data.get("has_tolls"),
        polyline=tuple(
            GeoPoint(
                latitude=Decimal(str(item[0])),
                longitude=Decimal(str(item[1])),
                normalized_name=str(item[2]),
                confidence=int(item[3]),
            )
            for item in data.get("polyline", ())
        ),
        supports_truck_restrictions=bool(data["supports_truck_restrictions"]),
        traffic_aware=bool(data["traffic_aware"]),
        toll_information_available=bool(data["toll_information_available"]),
        metadata={str(key): str(value) for key, value in data.get("metadata", {}).items()},
    )
