"""Доменные модели маршрутов (Stage 8.5).

Деньги — Decimal, физика (километры, часы) — float. Провайдер карт знает
только геометрию (расстояние, время, уверенность, иногда платные участки);
деньги досчитывает RouteCostCalculator по политике пользователя — поэтому
денежные поля оценки имеют дефолт 0 и уточняются через ``dataclasses.replace``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.logistics.vehicle_profile import VehicleProfile

#: Уверенность провайдера карт (точный маршрут по дорогам).
PROVIDER_CONFIDENCE = 90
#: Уверенность синтетической оценки (расстояние из объявления, время по средней скорости).
SYNTHETIC_CONFIDENCE = 40


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """Географическая точка WGS84 после геокодирования."""

    latitude: Decimal
    longitude: Decimal
    normalized_name: str = ""
    confidence: int = 100

    @property
    def yandex_pair(self) -> str:
        """Формат Yandex Router: latitude,longitude."""
        return f"{self.latitude},{self.longitude}"

    @property
    def osrm_pair(self) -> str:
        """Формат OSRM: longitude,latitude."""
        return f"{self.longitude},{self.latitude}"


@dataclass(frozen=True, slots=True)
class RouteVehicleParameters:
    """Нейтральные параметры грузовика для infrastructure-провайдеров."""

    actual_weight_tons: Decimal | None = None
    max_weight_tons: Decimal | None = None
    payload_tons: Decimal | None = None
    axle_weight_tons: Decimal | None = None
    height_m: Decimal | None = None
    width_m: Decimal | None = None
    length_m: Decimal | None = None
    vehicle_permits: tuple[str, ...] = ()
    has_trailer: bool = False
    eco_class: int | None = None

    @classmethod
    def from_profile(cls, profile: VehicleProfile | None) -> RouteVehicleParameters | None:
        """Перевести VehicleProfile в нейтральные параметры без передачи профиля в infra."""
        if profile is None:
            return None

        def kg_to_tons(value: int | None) -> Decimal | None:
            return Decimal(value) / Decimal(1000) if value is not None else None

        def cm_to_m(value: int) -> Decimal:
            return Decimal(value) / Decimal(100)

        actual_kg = (
            profile.empty_weight_kg + profile.cargo_capacity_kg
            if profile.empty_weight_kg is not None
            else profile.max_weight_kg
        )
        return cls(
            actual_weight_tons=kg_to_tons(actual_kg),
            max_weight_tons=kg_to_tons(profile.max_weight_kg),
            payload_tons=kg_to_tons(profile.cargo_capacity_kg),
            axle_weight_tons=kg_to_tons(profile.axle_weight_kg),
            height_m=cm_to_m(profile.height_cm),
            width_m=cm_to_m(profile.width_cm),
            length_m=cm_to_m(profile.length_cm),
            vehicle_permits=profile.vehicle_permits,
            has_trailer=profile.has_trailer,
            eco_class=profile.eco_class,
        )


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """Расширенный запрос маршрута для production-провайдеров."""

    origin: str
    destination: str
    origin_point: GeoPoint | None = None
    destination_point: GeoPoint | None = None
    vehicle: RouteVehicleParameters | None = None
    departure_at: datetime | None = None
    avoid_tolls: bool = False
    avoid_unpaved: bool = False
    alternatives: int = 1
    traffic_enabled: bool = True

    @classmethod
    def simple(cls, origin: str, destination: str) -> RouteRequest:
        """Совместимый запрос только из строк."""
        return cls(origin=origin, destination=destination)


@dataclass(frozen=True, slots=True)
class RouteEstimate:
    """Оценка маршрута: геометрия провайдера + стоимости по политике.

    ``confidence_score`` 0–100: 100 — тривиальный маршрут (точка совпадает),
    ~90 — провайдер карт, ~40 — синтетическая оценка по объявлению.
    """

    distance_km: float
    duration_hours: float
    fuel_cost: Decimal = Decimal(0)
    toll_cost: Decimal = Decimal(0)
    driver_cost: Decimal = Decimal(0)
    maintenance_cost: Decimal = Decimal(0)
    total_cost: Decimal = Decimal(0)
    confidence_score: int = PROVIDER_CONFIDENCE
    provider: str = "mock"
    provider_label: str = "Mock"
    is_fallback: bool = False
    warnings: tuple[str, ...] = ()
    calculated_at: datetime = field(default_factory=utc_now)
    traffic_duration_hours: float | None = None
    has_tolls: bool | None = None
    polyline: tuple[GeoPoint, ...] = ()
    supports_truck_restrictions: bool = False
    traffic_aware: bool = False
    toll_information_available: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Route:
    """Рассчитанный маршрут — запись факта (события, аналитика, будущий кэш)."""

    id: str
    from_location: str
    to_location: str
    distance_km: float
    estimated_hours: float
    toll_cost: Decimal
    fuel_cost: Decimal
    provider: str = "unknown"
    provider_label: str = "Unknown"
    confidence_score: int = 0
    is_fallback: bool = False
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, from_location: str, to_location: str, estimate: RouteEstimate) -> Route:
        """Собрать запись маршрута из готовой оценки."""
        return cls(
            id=uuid4().hex,
            from_location=from_location,
            to_location=to_location,
            distance_km=estimate.distance_km,
            estimated_hours=estimate.duration_hours,
            toll_cost=estimate.toll_cost,
            fuel_cost=estimate.fuel_cost,
            provider=estimate.provider,
            provider_label=estimate.provider_label,
            confidence_score=estimate.confidence_score,
            is_fallback=estimate.is_fallback,
        )
