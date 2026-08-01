"""CargoSearchEngine — чистый движок подбора (без I/O).

Вход: профиль транспорта + список грузов + запрос.
Выход: SearchResult. Движок не знает ни ATI, ни Telegram, ни SQLite, ни UI.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile
from app.core.models.search import CargoMatch, CargoSearchQuery, SearchResult
from app.services.logistics.compatibility_service import CargoCompatibilityService
from app.services.search.prefilter import CargoPreFilter
from app.services.search.ranking import CargoRankingService
from app.services.search.scoring import CargoScoreCalculator


class CargoSearchEngine:
    """Пайплайн: PreFilter → Compatibility → Scoring → Ranking."""

    def __init__(
        self,
        *,
        prefilter: CargoPreFilter,
        compatibility: CargoCompatibilityService,
        scorer: CargoScoreCalculator,
        ranking: CargoRankingService,
    ) -> None:
        self._prefilter = prefilter
        self._compatibility = compatibility
        self._scorer = scorer
        self._ranking = ranking

    def search(
        self,
        query: CargoSearchQuery,
        vehicle: VehicleProfile,
        cargos: Sequence[Cargo],
        *,
        trace_id: str = "",
    ) -> SearchResult:
        """Оценить кандидатов и вернуть ранжированный результат."""
        matches: list[CargoMatch] = []
        prefiltered_out = 0
        for cargo in cargos:
            passed, _reason = self._prefilter.passes(cargo, query)
            if not passed:
                prefiltered_out += 1
                continue
            matches.append(self.match_single(cargo, vehicle, query))
        return SearchResult(
            query_id=query.id,
            trace_id=trace_id,
            total_candidates=len(cargos),
            prefiltered_out=prefiltered_out,
            matches=self._ranking.rank(tuple(matches)),
        )

    def match_single(
        self, cargo: Cargo, vehicle: VehicleProfile, query: CargoSearchQuery
    ) -> CargoMatch:
        """Оценить один груз (совместимость + балл)."""
        compatibility = self._compatibility.check(cargo, vehicle)
        return CargoMatch(
            cargo_id=cargo.id,
            vehicle_profile_id=vehicle.id,
            compatible=compatibility.compatible,
            compatibility_result=compatibility,
            score=self._scorer.score(cargo, compatibility, query),
            cargo=cargo,
        )
