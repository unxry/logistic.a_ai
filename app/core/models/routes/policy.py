"""Политика стоимости маршрута — все параметры пользовательские (настройки).

Дефолты дают эталон ТЗ (Москва → Санкт-Петербург, 710 км, 10 ч):
топливо 30 л/100 км × 70 ₽/л = 14 910 ₽, платные 9 ₽/км = 6 390 ₽,
обслуживание 10 ₽/км = 7 100 ₽, водитель 660 ₽/ч = 6 600 ₽ —
итого 35 000 ₽ расходов, чистая прибыль 85 000 ₽ при доходе 120 000 ₽.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import Enum


class RouteProviderChoice(Enum):
    """Выбор production-провайдера маршрутов."""

    AUTO = "auto"
    YANDEX = "yandex"
    OSRM = "osrm"
    MOCK = "mock"


@dataclass(frozen=True, slots=True)
class RouteCostPolicy:
    """Параметры экономики рейса (деньги — Decimal, скорость — float)."""

    fuel_consumption_l_per_100km: Decimal = Decimal(30)
    fuel_price_per_liter: Decimal = Decimal(70)
    toll_cost_per_km: Decimal = Decimal(9)
    maintenance_cost_per_km: Decimal = Decimal(10)
    driver_cost_per_hour: Decimal = Decimal(660)
    average_speed_kmh: float = 71.0  # для оценки времени, когда провайдера нет
    provider: RouteProviderChoice = RouteProviderChoice.AUTO
    yandex_credentials_reference: str = "yandex_routes"
    osrm_base_url: str = "https://router.project-osrm.org"
    traffic_enabled: bool = True
    avoid_tolls: bool = False
    avoid_unpaved: bool = False
    alternatives_count: int = 1
    cache_enabled: bool = True
    fallback_enabled: bool = True

    def __post_init__(self) -> None:
        """Отрицательные тарифы и нулевая скорость — ошибка конфигурации."""
        money = (
            self.fuel_consumption_l_per_100km,
            self.fuel_price_per_liter,
            self.toll_cost_per_km,
            self.maintenance_cost_per_km,
            self.driver_cost_per_hour,
        )
        if any(value < 0 for value in money):
            raise ValueError("Параметры стоимости маршрута не могут быть отрицательными")
        if self.average_speed_kmh <= 0:
            raise ValueError("Средняя скорость должна быть положительной")
        if self.alternatives_count < 1 or self.alternatives_count > 3:
            raise ValueError("Количество альтернатив маршрута должно быть от 1 до 3")

    @property
    def fuel_consumption_km_per_liter(self) -> Decimal:
        """Пробег на литр — знаменатель формулы ТЗ.

        fuel_cost = distance_km / fuel_consumption(км/л) × fuel_price.
        """
        return Decimal(100) / self.fuel_consumption_l_per_100km

    @property
    def fuel_cost_per_km(self) -> Decimal:
        """Стоимость километра по топливу."""
        return self.fuel_consumption_l_per_100km * self.fuel_price_per_liter / Decimal(100)


@dataclass(frozen=True, slots=True)
class RouteCachePolicy:
    """TTL-политика route/geocoding cache (репозиторий TTL не хардкодит)."""

    yandex_traffic_ttl: timedelta = timedelta(minutes=45)
    yandex_static_ttl: timedelta = timedelta(days=7)
    osrm_ttl: timedelta = timedelta(days=30)
    geocoding_ttl: timedelta = timedelta(days=90)

    def route_ttl(self, *, provider: str, traffic_aware: bool) -> timedelta:
        """TTL для route estimate по типу провайдера."""
        if provider == "yandex":
            return self.yandex_traffic_ttl if traffic_aware else self.yandex_static_ttl
        if provider == "osrm":
            return self.osrm_ttl
        return self.osrm_ttl
