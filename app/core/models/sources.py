"""Модели платформы источников грузов.

Источник — данные (SourceSpec) + корутина fetch(context) → SourceResult
с «сырыми» грузами (RawCargo). Пользовательская настройка источника —
SourceConfiguration (секретов не содержит — только ссылку на SecretStore).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from logging import Logger
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.logistics.cargo import Cargo
from app.core.models.scheduler import Interval, JobRetryPolicy, JobSchedule
from app.core.models.settings import AppSettings


class SourceType(Enum):
    """Тип источника."""

    API = "api"
    BROWSER = "browser"
    FILE_IMPORT = "file_import"
    PLUGIN = "plugin"
    OTHER = "other"


class SourceStatus(Enum):
    """Состояние здоровья источника."""

    ONLINE = "online"
    AUTHENTICATED_NO_MARKET_ACCESS = "authenticated_no_market_access"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISABLED = "disabled"


class AtiTokenState(Enum):
    """Состояние временного ATI access_token."""

    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class AtiTokenStatus:
    """Безопасный статус ATI-токена без значения секрета."""

    state: AtiTokenState
    expires_at: datetime | None = None
    masked_token: str = ""

    @property
    def can_use(self) -> bool:
        """Можно ли делать API-запрос с этим токеном."""
        return self.state in (AtiTokenState.VALID, AtiTokenState.EXPIRING_SOON)


@dataclass(frozen=True, slots=True)
class AtiPipelineReport:
    """Подробный отчёт live ATI-конвейера за один poll."""

    trace_id: str
    started_at: datetime
    finished_at: datetime
    pages_requested: int = 0
    raw_received: int = 0
    mapped: int = 0
    normalization_failed: int = 0
    duplicates: int = 0
    updated: int = 0
    prefilter_rejected: int = 0
    compatibility_rejected: int = 0
    matched: int = 0
    ranked: int = 0
    notifications_created: int = 0
    telegram_sent: int = 0
    telegram_failed: int = 0
    best_cargo_id: str = ""

    @property
    def duration_seconds(self) -> float:
        """Длительность poll в секундах."""
        return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True, slots=True)
class LivePipelineReport:
    """Commissioning-отчёт полного live E2E без секретов и персональных данных."""

    trace_id: str
    started_at: datetime
    finished_at: datetime
    ati_authenticated: bool = False
    ati_endpoint: str = ""
    ati_board_id_masked: str = ""
    ati_pages: int = 0
    raw_received: int = 0
    mapped: int = 0
    normalized: int = 0
    invalid: int = 0
    duplicates: int = 0
    updated: int = 0
    prefilter_rejected: int = 0
    compatibility_rejected: int = 0
    routes_requested: int = 0
    route_cache_hits: int = 0
    route_fallbacks: int = 0
    matched: int = 0
    best_cargo_id: str = ""
    best_score: int = 0
    best_net_profit: str = ""
    notifications_created: int = 0
    telegram_sent: int = 0
    telegram_failed: int = 0
    duration_ms: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SourceCapabilities:
    """Возможности источника (Search Engine поймёт доступные фильтры)."""

    supports_weight: bool = False
    supports_dimensions: bool = False
    supports_volume: bool = False
    supports_regions: bool = False
    supports_temperature: bool = False
    supports_pallets: bool = False
    supports_price: bool = False
    supports_live_updates: bool = False
    supports_documents: bool = False


@dataclass(frozen=True, slots=True)
class SourceRateLimitPolicy:
    """Ограничение частоты обращений к источнику (token bucket)."""

    requests_per_minute: int = 60
    burst_limit: int = 10


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Полное описание источника — только данные.

    ``enabled`` — заводское значение поставщика источника; пользовательская
    конфигурация (SourceConfiguration) имеет приоритет. Скелеты реальных
    источников поставляются с ``enabled=False`` — их включает пользователь.
    """

    id: str
    name: str
    version: str = "1.0"
    enabled: bool = True
    source_type: SourceType = SourceType.API
    capabilities: SourceCapabilities = field(default_factory=SourceCapabilities)
    schedule: JobSchedule = field(default_factory=lambda: Interval(seconds=60.0))
    timeout_seconds: float | None = 30.0
    retry_policy: JobRetryPolicy = field(default_factory=JobRetryPolicy)
    rate_limit: SourceRateLimitPolicy = field(default_factory=SourceRateLimitPolicy)
    requires_credentials: bool = False
    supported_regions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Каталожная карточка источника (для UI «доступные источники»)."""

    id: str
    name: str
    version: str
    source_type: SourceType
    capabilities: SourceCapabilities
    requires_credentials: bool
    supported_regions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceConfiguration:
    """Пользовательская настройка источника.

    Секреты здесь НЕ хранятся — только ``credentials_reference`` (ссылка,
    по которой SourceCredentialProvider достаёт значения из SecretStore).
    ``filters`` — сырые пользовательские фильтры источника (регион, радиус…).
    """

    id: str
    source_id: str
    enabled: bool
    name: str
    credentials_reference: str = ""
    polling_interval_seconds: int = 300
    max_results: int = 100
    filters: Mapping[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        source_id: str,
        *,
        name: str = "",
        enabled: bool = True,
        credentials_reference: str = "",
        polling_interval_seconds: int = 300,
        max_results: int = 100,
        filters: Mapping[str, str] | None = None,
    ) -> SourceConfiguration:
        """Создать конфигурацию с новым id и текущим временем UTC."""
        return cls(
            id=uuid4().hex,
            source_id=source_id,
            enabled=enabled,
            name=name or source_id,
            credentials_reference=credentials_reference,
            polling_interval_seconds=polling_interval_seconds,
            max_results=max_results,
            filters=filters if filters is not None else {},
        )


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Что источник получает от runtime (намеренно мало).

    Уведомления и журнал источнику не выдаются — этим занимается runtime.
    ``configuration`` — пользовательская настройка (max_results, filters,
    credentials_reference); ``None`` — конфигурации нет.
    """

    logger: Logger
    settings: Callable[[], AppSettings]
    clock: Callable[[], datetime] = utc_now
    trace_id: str = ""
    configuration: SourceConfiguration | None = None


# Общеизвестные ключи атрибутов RawCargo (контракт нормализатора).
ATTR_WEIGHT = "weight"
ATTR_LENGTH = "length"
ATTR_WIDTH = "width"
ATTR_HEIGHT = "height"
ATTR_VOLUME = "volume"
ATTR_PALLETS = "pallets"
ATTR_CATEGORY = "category"
ATTR_BODY_TYPE = "body_type"
ATTR_LOADING_REGION = "loading_region"
ATTR_UNLOADING_REGION = "unloading_region"
ATTR_PRICE = "price"
ATTR_DISTANCE_KM = "distance_km"


@dataclass(frozen=True, slots=True)
class RawCargo:
    """«Сырой» груз, как его отдал источник (до нормализации)."""

    external_id: str
    title: str = ""
    url: str = ""
    attributes: Mapping[str, str] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceResult:
    """Единый результат fetch() любого источника."""

    source_id: str
    received_at: datetime
    raw_items: tuple[RawCargo, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    duration_ms: int = 0
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class SourceMetrics:
    """Накопленные метрики источника (неизменяемый снапшот)."""

    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_cargo_received: int = 0
    total_duration_ms: int = 0
    last_run: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Доля успешных запусков (0.0, если запусков не было)."""
        if self.total_runs == 0:
            return 0.0
        return self.successful_runs / self.total_runs

    @property
    def average_duration_ms(self) -> float:
        """Средняя длительность запуска."""
        if self.total_runs == 0:
            return 0.0
        return self.total_duration_ms / self.total_runs


@dataclass(frozen=True, slots=True)
class SourceHealth:
    """Здоровье источника для Dashboard и мониторинга.

    Stage 9.6 (production-метрики, аддитивно): длительность последнего
    успешного опроса, пропускная способность, доли дублей и ошибок.
    ``average_duration_ms`` — средний отклик (avg_response_time).
    """

    status: SourceStatus
    last_success: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    consecutive_failures: int = 0
    success_rate: float = 0.0
    average_duration_ms: float = 0.0
    items_received: int = 0
    last_received_count: int = 0
    last_success_duration_ms: int = 0
    cargos_per_hour: float = 0.0
    duplicate_rate: float = 0.0
    error_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class SourceRunReport:
    """Итог одного запуска источника (после нормализации)."""

    source_id: str
    success: bool
    trace_id: str
    duration_ms: int
    items: tuple[Cargo, ...] = ()
    raw_count: int = 0
    warnings: tuple[str, ...] = ()
    error: str | None = None
    attempts: int = 1
