"""Search Engine — headless-поиск и подбор грузов под профиль транспорта.

Пайплайн: PreFilter → CompatibilityService → ScoreCalculator → Ranking →
SearchResult. Каждый шаг — отдельный заменяемый класс.
"""

from app.services.search.engine import CargoSearchEngine
from app.services.search.matching_service import CargoMatchingService
from app.services.search.pipeline import PipelineReport, RecommendationPipeline
from app.services.search.prefilter import CargoPreFilter
from app.services.search.ranking import CargoRankingService
from app.services.search.scoring import CargoScoreCalculator, ScoringWeights

__all__ = [
    "CargoMatchingService",
    "CargoPreFilter",
    "CargoRankingService",
    "CargoScoreCalculator",
    "CargoSearchEngine",
    "PipelineReport",
    "RecommendationPipeline",
    "ScoringWeights",
]
