"""AtiSource — источник ATI.SU (реализация порта CargoSource, Stage 9.5).

Источник добывает данные и ничего больше: ретраи, rate limit, здоровье,
журнал и уведомления — забота SourceRuntime. Клиент передаётся из
composition root (один httpx-клиент на процесс, graceful aclose).
"""

from __future__ import annotations

from time import perf_counter

from app.core.errors import SourceAuthenticationError
from app.core.models.scheduler import Interval, JobRetryPolicy
from app.core.models.sources import (
    SourceCapabilities,
    SourceContext,
    SourceRateLimitPolicy,
    SourceResult,
    SourceSpec,
    SourceType,
)
from app.core.ports import SourceCredentialProvider
from app.infrastructure.sources.ati.client import AtiClient
from app.infrastructure.sources.ati.mapper import AtiCargoMapper

SOURCE_ID = "ati"

_SPEC = SourceSpec(
    id=SOURCE_ID,
    name="ATI.SU",
    version="1.0",
    enabled=False,  # включается ТОЛЬКО пользовательской конфигурацией
    source_type=SourceType.API,
    capabilities=SourceCapabilities(
        supports_weight=True,
        supports_dimensions=True,
        supports_volume=True,
        supports_regions=True,
        supports_price=True,
        supports_pallets=True,
    ),
    schedule=Interval(seconds=300.0, run_immediately=False),  # ATI-POLL: каждые 5 минут
    timeout_seconds=30.0,
    retry_policy=JobRetryPolicy(max_attempts=3, delay_seconds=1.0),
    rate_limit=SourceRateLimitPolicy(requests_per_minute=30, burst_limit=5),
    requires_credentials=True,
    supported_regions=("RU", "BY", "KZ"),
)


class AtiSource:
    """CargoSource для ATI.SU."""

    def __init__(
        self,
        credentials: SourceCredentialProvider,
        client: AtiClient | None = None,
    ) -> None:
        self._client = client if client is not None else AtiClient(credentials)
        self._mapper = AtiCargoMapper()

    @property
    def spec(self) -> SourceSpec:
        """Описание источника."""
        return _SPEC

    def credential_status(self, reference: str) -> object:
        """Статус ATI-токена без раскрытия секрета (для SourceRuntime)."""
        return self._client.token_status(reference)

    async def fetch(self, context: SourceContext) -> SourceResult:
        """Получить грузы ATI по пользовательской конфигурации."""
        started = perf_counter()
        configuration = context.configuration
        reference = configuration.credentials_reference if configuration is not None else ""
        max_results = configuration.max_results if configuration is not None else 100
        filters = dict(configuration.filters) if configuration is not None else {}

        if not self._client.has_credentials(reference):
            raise SourceAuthenticationError(
                "Учётные данные ATI не настроены — добавьте access_token или login+password"
                " в Keychain и укажите credentials_reference в конфигурации источника"
            )

        payloads = await self._client.search_cargo(
            credentials_reference=reference, max_results=max_results, filters=filters
        )
        raw_items = tuple(self._mapper.map(payload) for payload in payloads)
        return SourceResult(
            source_id=SOURCE_ID,
            received_at=context.clock(),
            raw_items=raw_items,
            duration_ms=int((perf_counter() - started) * 1000),
            trace_id=context.trace_id,
        )
