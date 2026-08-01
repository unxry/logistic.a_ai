"""Модели поиска и подбора грузов (Search Engine, Stage 6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.compatibility import CompatibilityResult
from app.core.models.logistics.vehicle_profile import BodyType


@dataclass(frozen=True, slots=True)
class CargoSearchQuery:
    """Пользовательский запрос поиска грузов под профиль транспорта.

    Пустые кортежи/None означают «без ограничения по этому критерию».
    """

    id: str
    vehicle_profile_id: str
    categories: tuple[CargoCategory, ...] = ()
    regions: tuple[str, ...] = ()
    min_price: Decimal | None = None
    max_distance_km: float | None = None
    min_weight_kg: int | None = None
    max_weight_kg: int | None = None
    required_body_types: tuple[BodyType, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        vehicle_profile_id: str,
        *,
        categories: tuple[CargoCategory, ...] = (),
        regions: tuple[str, ...] = (),
        min_price: Decimal | None = None,
        max_distance_km: float | None = None,
        min_weight_kg: int | None = None,
        max_weight_kg: int | None = None,
        required_body_types: tuple[BodyType, ...] = (),
    ) -> CargoSearchQuery:
        """Создать запрос с новым id."""
        return cls(
            id=uuid4().hex,
            vehicle_profile_id=vehicle_profile_id,
            categories=categories,
            regions=regions,
            min_price=min_price,
            max_distance_km=max_distance_km,
            min_weight_kg=min_weight_kg,
            max_weight_kg=max_weight_kg,
            required_body_types=required_body_types,
        )


@dataclass(frozen=True, slots=True)
class CargoMatch:
    """Результат подбора одного груза под профиль."""

    cargo_id: str
    vehicle_profile_id: str
    compatible: bool
    compatibility_result: CompatibilityResult
    score: int
    cargo: Cargo
    estimated_profit: Decimal | None = None  # заполнит Stage 9 (экономика рейса)
    ranking_position: int = 0


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Итог поиска: оценённые и ранжированные грузы."""

    query_id: str
    trace_id: str
    total_candidates: int
    prefiltered_out: int
    matches: tuple[CargoMatch, ...]
    created_at: datetime = field(default_factory=utc_now)

    @property
    def compatible_matches(self) -> tuple[CargoMatch, ...]:
        """Только совместимые (уже отранжированы лучшие первыми)."""
        return tuple(match for match in self.matches if match.compatible)

    @property
    def best(self) -> CargoMatch | None:
        """Лучший совместимый груз."""
        compatible = self.compatible_matches
        return compatible[0] if compatible else None
