"""PreferenceEngine — оценка груза относительно предпочтений водителя.

Балльная система v1 (без ML): база 50, бонусы/штрафы за совпадения.
Запрещённый регион — жёсткий отказ (rejected), а не штраф.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models.logistics.driver_profile import DriverProfile
from app.core.models.search import CargoMatch

_BASE = 50
_REGION_BONUS = 20
_CATEGORY_BONUS = 15
_BODY_BONUS = 10
_DISTANCE_BONUS = 10
_LOW_RATE_PENALTY = 30


@dataclass(frozen=True, slots=True)
class PreferenceVerdict:
    """Итог оценки предпочтений."""

    score: int
    notes: tuple[str, ...] = ()
    rejected_reason: str = ""

    @property
    def rejected(self) -> bool:
        """Груз отклонён предпочтениями."""
        return bool(self.rejected_reason)


class PreferenceEngine:
    """Сопоставление груза с DriverProfile."""

    def evaluate(self, match: CargoMatch, driver: DriverProfile) -> PreferenceVerdict:
        """Оценить груз; запрещённый регион — отказ."""
        cargo = match.cargo
        for region in (cargo.loading_region, cargo.unloading_region):
            if region and region in driver.forbidden_regions:
                return PreferenceVerdict(score=0, rejected_reason=f"Запрещённый регион «{region}»")

        score = _BASE
        notes: list[str] = []
        if driver.preferred_regions and (
            cargo.loading_region in driver.preferred_regions
            or cargo.unloading_region in driver.preferred_regions
        ):
            score += _REGION_BONUS
            notes.append("Ваше направление")
        if cargo.category in driver.preferred_cargo_categories:
            score += _CATEGORY_BONUS
            notes.append("Любимая категория груза")
        if (
            cargo.required_body_type is not None
            and cargo.required_body_type in driver.preferred_body_types
        ):
            score += _BODY_BONUS
        if (
            driver.preferred_distance_km is not None
            and cargo.distance_km is not None
            and abs(cargo.distance_km - driver.preferred_distance_km)
            <= driver.preferred_distance_km * 0.3
        ):
            score += _DISTANCE_BONUS
            notes.append("Комфортное плечо")
        if (
            driver.minimum_price_per_km is not None
            and cargo.payment_amount is not None
            and cargo.distance_km is not None
            and cargo.distance_km > 0
            and cargo.payment_amount / Decimal(str(cargo.distance_km)) < driver.minimum_price_per_km
        ):
            score -= _LOW_RATE_PENALTY
            notes.append("Ставка ниже вашего минимума")
        return PreferenceVerdict(score=max(0, min(100, score)), notes=tuple(notes))
