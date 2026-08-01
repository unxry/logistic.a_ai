"""ATI.SU — production-адаптер источника грузов (Stage 9.5)."""

from app.infrastructure.sources.ati.auth import AtiAuthProvider
from app.infrastructure.sources.ati.client import AtiClient
from app.infrastructure.sources.ati.mapper import AtiCargoMapper
from app.infrastructure.sources.ati.source import SOURCE_ID, AtiSource
from app.infrastructure.sources.ati.url_builder import AtiCargoUrlBuilder

__all__ = [
    "SOURCE_ID",
    "AtiAuthProvider",
    "AtiCargoMapper",
    "AtiCargoUrlBuilder",
    "AtiClient",
    "AtiSource",
]
