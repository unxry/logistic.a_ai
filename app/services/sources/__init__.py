"""Платформа источников грузов: реестр, нормализатор, дедупликация, runtime.

Новый источник (ATI, Ozon, WB, CSV, плагин) = один класс, реализующий порт
CargoSource, + регистрация. Search Engine, Scheduler и Notification Center
при этом не меняются.
"""

from app.services.sources.dedup import (
    CargoDeduplicationService,
    CargoDeduplicator,
    DeduplicationStatus,
    DeduplicationVerdict,
    cargo_fingerprint,
)
from app.services.sources.normalizer import CargoNormalizer
from app.services.sources.registry import SourceRegistry
from app.services.sources.runtime import SourcePollJob, SourceRuntime

__all__ = [
    "CargoDeduplicationService",
    "CargoDeduplicator",
    "CargoNormalizer",
    "DeduplicationStatus",
    "DeduplicationVerdict",
    "SourcePollJob",
    "SourceRegistry",
    "SourceRuntime",
    "cargo_fingerprint",
]
