"""SourceRuntime — исполнитель опроса источников.

Ответственность: эффективная конфигурация (пользовательская поверх spec),
rate limit (token bucket + уважение retry_after), запуск fetch с таймаутом
и ретраями, нормализация, здоровье и метрики, журнал (SOURCE_EVENT), события
и уведомления об ошибках через Notification Center. Источник ничего этого
не знает — он только добывает данные.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from time import perf_counter
from uuid import uuid4

from app.core.clock import utc_now
from app.core.errors import SourceError, SourceRateLimitError, StorageError
from app.core.events import CargoReceived, SourceCompleted, SourceFailed, SourceHealthChanged
from app.core.events.sources import SourceStarted as SourceStartedEvent
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.logistics.cargo import Cargo
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.scheduler import Interval, JobContext, JobRetryPolicy, JobSchedule, JobSpec
from app.core.models.settings import AppSettings
from app.core.models.severity import Severity
from app.core.models.sources import (
    AtiTokenState,
    AtiTokenStatus,
    SourceConfiguration,
    SourceContext,
    SourceHealth,
    SourceMetrics,
    SourceResult,
    SourceRunReport,
    SourceSpec,
    SourceStatus,
)
from app.core.ports import (
    CargoSource,
    EventPublisher,
    HistoryRepository,
    NotificationSender,
    SourceConfigurationRepository,
)
from app.services.notifications.cooldown import NotificationCooldownPolicy
from app.services.sources.normalizer import CargoNormalizer
from app.services.sources.rate_limiter import SourceRateLimiter
from app.services.sources.registry import SourceRegistry

logger = logging.getLogger(__name__)

_SOURCE = "sources"
_DEGRADED_BELOW = 0.8  # success_rate ниже порога при успешном последнем запуске
_RATE_WAIT_NOTIFY_SECONDS = 10.0  # ожидание лимитера дольше — уведомляем


class SourceRuntime:
    """Запуск источников: конфигурация, лимиты, надзор, наблюдаемость."""

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        normalizer: CargoNormalizer,
        event_bus: EventPublisher,
        notifications: NotificationSender,
        history: HistoryRepository,
        settings_provider: Callable[[], AppSettings],
        configurations: SourceConfigurationRepository | None = None,
        clock: Callable[[], datetime] = utc_now,
        failure_cooldown: NotificationCooldownPolicy | None = None,
        duplicates_provider: Callable[[str], int] | None = None,
    ) -> None:
        self._registry = registry
        self._normalizer = normalizer
        self._events = event_bus
        self._notifications = notifications
        self._history = history
        self._settings_provider = settings_provider
        self._configurations = configurations
        self._clock = clock

        self._metrics: dict[str, SourceMetrics] = {}
        self._health: dict[str, SourceHealth] = {}
        self._last_success: dict[str, datetime] = {}
        self._last_error_at: dict[str, datetime] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._last_received: dict[str, int] = {}
        self._limiters: dict[str, SourceRateLimiter] = {}
        self._first_run: dict[str, datetime] = {}
        self._last_success_duration: dict[str, int] = {}
        self._cooldown = (
            failure_cooldown
            if failure_cooldown is not None
            else NotificationCooldownPolicy(clock=clock)
        )
        self._duplicates_provider = duplicates_provider

    # ── Публичный контракт ────────────────────────────────────────────────────

    async def run_source(self, source_id: str, trace_id: str | None = None) -> SourceRunReport:
        """Опросить источник: лимиты → fetch → нормализация → наблюдаемость."""
        source = self._registry.get(source_id)
        spec = source.spec
        configuration = self._configuration(source_id)
        trace = trace_id if trace_id else uuid4().hex

        if not self._effective_enabled(spec, configuration):
            self._set_health(source_id, SourceStatus.DISABLED, last_error=None)
            return SourceRunReport(
                source_id=source_id,
                success=False,
                trace_id=trace,
                duration_ms=0,
                error="Источник выключен",
                attempts=0,
            )

        logger.info("Источник «%s»: опрос начат", source_id)
        self._events.publish(SourceStartedEvent(source_id=source_id, trace_id=trace))
        started = perf_counter()

        token_status = self._credential_status(source, configuration)
        if token_status is not None:
            if token_status.state is AtiTokenState.EXPIRED:
                duration_ms = int((perf_counter() - started) * 1000)
                await self._notify_ati_token_expired(spec, trace)
                return await self._finish_failure(
                    spec,
                    trace,
                    duration_ms,
                    "ATI access_token истёк — обновите токен в настройках",
                    0,
                )
            if token_status.state is AtiTokenState.EXPIRING_SOON:
                await self._notify_ati_token_expiring(spec, trace)

        result, error, attempts = await self._fetch_with_policy(source, trace, configuration)
        duration_ms = int((perf_counter() - started) * 1000)

        if result is None:
            return await self._finish_failure(
                spec, trace, duration_ms, error or "неизвестная ошибка", attempts
            )
        return await self._finish_success(spec, trace, duration_ms, result, attempts)

    def build_jobs(self) -> tuple[SourcePollJob, ...]:
        """Job-адаптеры для Scheduler'а (по одному на включённый источник).

        Интервал опроса из пользовательской конфигурации имеет приоритет
        над заводским расписанием spec.
        """
        jobs: list[SourcePollJob] = []
        for source in self._registry.all():
            spec = source.spec
            configuration = self._configuration(spec.id)
            if not self._effective_enabled(spec, configuration):
                continue
            schedule = spec.schedule
            if configuration is not None:
                schedule = Interval(
                    seconds=float(configuration.polling_interval_seconds),
                    run_immediately=False,
                )
            jobs.append(SourcePollJob(self, spec, schedule))
        return tuple(jobs)

    def health(self, source_id: str) -> SourceHealth:
        """Здоровье источника."""
        return self._health.get(source_id, SourceHealth(status=SourceStatus.DISABLED))

    def metrics(self, source_id: str) -> SourceMetrics:
        """Метрики источника."""
        return self._metrics.get(source_id, SourceMetrics())

    # ── Исполнение ────────────────────────────────────────────────────────────

    async def _fetch_with_policy(
        self,
        source: CargoSource,
        trace: str,
        configuration: SourceConfiguration | None,
    ) -> tuple[SourceResult | None, str | None, int]:
        """Fetch с rate limit, таймаутом и ретраями из SourceSpec."""
        spec = source.spec
        retry: JobRetryPolicy = spec.retry_policy
        limiter = self._limiter(spec)
        context = SourceContext(
            logger=logging.getLogger(f"app.sources.{spec.id}"),
            settings=self._settings_provider,
            clock=self._clock,
            trace_id=trace,
            configuration=configuration,
        )
        error: str | None = None
        retry_after: float | None = None
        for attempt in range(1, retry.max_attempts + 1):
            waited = await limiter.acquire(spec.id)
            if waited > _RATE_WAIT_NOTIFY_SECONDS:
                await self._notify_rate_limited(spec, trace, waited)
            try:
                if spec.timeout_seconds is not None:
                    result = await asyncio.wait_for(
                        source.fetch(context), timeout=spec.timeout_seconds
                    )
                else:
                    result = await source.fetch(context)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                error = f"Источник не ответил за {spec.timeout_seconds} с"
                retry_after = None
            except SourceRateLimitError as exc:
                error = str(exc)
                retry_after = exc.retry_after  # уважаем паузу источника
            except SourceError as exc:
                error = str(exc)
                retry_after = None
            except Exception as exc:  # источник обязан бросать SourceError — страхуемся
                error = f"{type(exc).__name__}: {exc}"
                retry_after = None
            else:
                return result, None, attempt
            if attempt < retry.max_attempts:
                delay = retry_after if retry_after is not None else retry.delay_for(attempt)
                logger.warning(
                    "Источник «%s»: попытка %d/%d не удалась, повтор через %.1f с",
                    spec.id,
                    attempt,
                    retry.max_attempts,
                    delay,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
        return None, error, retry.max_attempts

    async def _finish_success(
        self,
        spec: SourceSpec,
        trace: str,
        duration_ms: int,
        result: SourceResult,
        attempts: int,
    ) -> SourceRunReport:
        was_failed = self._health.get(spec.id, SourceHealth(status=SourceStatus.DISABLED)).status
        items, warnings = self._normalize_all(result, spec.id)
        self._record_run(spec.id, success=True, duration_ms=duration_ms, items=len(items))
        self._refresh_health(spec.id, last_error=None)
        if was_failed is SourceStatus.FAILED:
            # Источник ожил: сообщаем и сбрасываем cooldown — следующая
            # авария уведомит немедленно, а не после окна.
            self._cooldown.reset(f"source-failure:{spec.id}")
            await self._notify_recovered(spec, trace)

        logger.info("Источник «%s»: получено %d грузов за %d мс", spec.id, len(items), duration_ms)
        await self._record_history(
            spec,
            trace,
            severity=Severity.INFO,
            title=f"Источник «{spec.name}»: получено грузов: {len(items)}",
            details=f"{duration_ms} мс, попыток: {attempts}"
            + (f". Предупреждений: {len(warnings)}" if warnings else ""),
        )
        self._events.publish(
            SourceCompleted(
                source_id=spec.id,
                trace_id=trace,
                items_count=len(items),
                duration_ms=duration_ms,
            )
        )
        if items:
            self._events.publish(CargoReceived(source_id=spec.id, trace_id=trace, items=items))
        return SourceRunReport(
            source_id=spec.id,
            success=True,
            trace_id=trace,
            duration_ms=duration_ms,
            items=items,
            raw_count=len(result.raw_items),
            warnings=tuple(warnings),
            attempts=attempts,
        )

    async def _finish_failure(
        self, spec: SourceSpec, trace: str, duration_ms: int, error: str, attempts: int
    ) -> SourceRunReport:
        self._record_run(spec.id, success=False, duration_ms=duration_ms, items=0)
        self._refresh_health(spec.id, last_error=error)

        logger.warning("Источник «%s»: ошибка — %s", spec.id, error)
        await self._record_history(
            spec,
            trace,
            severity=Severity.WARNING,
            title=f"Источник «{spec.name}»: ошибка опроса",
            details=f"{error}. Попыток: {attempts}",
        )
        self._events.publish(SourceFailed(source_id=spec.id, trace_id=trace, error=error))
        if self._cooldown.should_send(f"source-failure:{spec.id}"):
            await self._notify_failure(spec, trace, error, attempts)
        else:
            logger.info(
                "Источник «%s»: повторная ошибка в окне cooldown — уведомление подавлено",
                spec.id,
            )
        return SourceRunReport(
            source_id=spec.id,
            success=False,
            trace_id=trace,
            duration_ms=duration_ms,
            error=error,
            attempts=attempts,
        )

    def _normalize_all(
        self, result: SourceResult, source_id: str
    ) -> tuple[tuple[Cargo, ...], list[str]]:
        items: list[Cargo] = []
        warnings: list[str] = list(result.warnings)
        for raw in result.raw_items:
            try:
                items.append(self._normalizer.normalize(raw, source_id))
            except Exception as exc:  # битая карточка не роняет весь опрос
                warnings.append(f"Груз {raw.external_id or '<без id>'} пропущен: {exc}")
        return tuple(items), warnings

    # ── Конфигурация и лимиты ─────────────────────────────────────────────────

    def _configuration(self, source_id: str) -> SourceConfiguration | None:
        if self._configurations is None:
            return None
        try:
            return self._configurations.get(source_id)
        except StorageError:
            logger.exception("Не удалось прочитать конфигурацию источника «%s»", source_id)
            return None

    @staticmethod
    def _effective_enabled(spec: SourceSpec, configuration: SourceConfiguration | None) -> bool:
        """Пользовательская конфигурация имеет приоритет над заводским spec."""
        if configuration is not None:
            return configuration.enabled
        return spec.enabled

    def _limiter(self, spec: SourceSpec) -> SourceRateLimiter:
        limiter = self._limiters.get(spec.id)
        if limiter is None:
            limiter = SourceRateLimiter(spec.rate_limit)
            self._limiters[spec.id] = limiter
        return limiter

    @staticmethod
    def _credential_status(
        source: CargoSource, configuration: SourceConfiguration | None
    ) -> AtiTokenStatus | None:
        if configuration is None:
            return None
        status = getattr(source, "credential_status", None)
        if not callable(status):
            return None
        value = status(configuration.credentials_reference)
        return value if isinstance(value, AtiTokenStatus) else None

    # ── Здоровье, метрики, наблюдаемость ─────────────────────────────────────

    def _record_run(self, source_id: str, *, success: bool, duration_ms: int, items: int) -> None:
        metrics = self._metrics.get(source_id, SourceMetrics())
        now = self._clock()
        self._metrics[source_id] = replace(
            metrics,
            total_runs=metrics.total_runs + 1,
            successful_runs=metrics.successful_runs + (1 if success else 0),
            failed_runs=metrics.failed_runs + (0 if success else 1),
            total_cargo_received=metrics.total_cargo_received + items,
            total_duration_ms=metrics.total_duration_ms + duration_ms,
            last_run=now,
        )
        self._first_run.setdefault(source_id, now)
        if success:
            self._last_success[source_id] = now
            self._consecutive_failures[source_id] = 0
            self._last_received[source_id] = items
            self._last_success_duration[source_id] = duration_ms
        else:
            self._last_error_at[source_id] = now
            self._consecutive_failures[source_id] = self._consecutive_failures.get(source_id, 0) + 1

    def _refresh_health(self, source_id: str, *, last_error: str | None) -> None:
        metrics = self._metrics.get(source_id, SourceMetrics())
        if last_error is not None:
            status = SourceStatus.FAILED
        elif metrics.success_rate < _DEGRADED_BELOW:
            status = SourceStatus.DEGRADED
        else:
            status = SourceStatus.ONLINE
        self._set_health(source_id, status, last_error=last_error)

    def _set_health(self, source_id: str, status: SourceStatus, *, last_error: str | None) -> None:
        metrics = self._metrics.get(source_id, SourceMetrics())
        previous = self._health.get(source_id)
        self._health[source_id] = SourceHealth(
            status=status,
            last_success=self._last_success.get(source_id),
            last_error=last_error,
            last_error_at=self._last_error_at.get(source_id),
            consecutive_failures=self._consecutive_failures.get(source_id, 0),
            success_rate=metrics.success_rate,
            average_duration_ms=metrics.average_duration_ms,
            items_received=metrics.total_cargo_received,
            last_received_count=self._last_received.get(source_id, 0),
            last_success_duration_ms=self._last_success_duration.get(source_id, 0),
            cargos_per_hour=self._cargos_per_hour(source_id, metrics),
            duplicate_rate=self._duplicate_rate(source_id, metrics),
            error_rate=(metrics.failed_runs / metrics.total_runs if metrics.total_runs else 0.0),
        )
        if previous is None or previous.status is not status:
            self._events.publish(SourceHealthChanged(source_id=source_id, status=status))

    def _cargos_per_hour(self, source_id: str, metrics: SourceMetrics) -> float:
        """Пропускная способность; до первой минуты работы — 0 (мало данных)."""
        first = self._first_run.get(source_id)
        if first is None or metrics.total_cargo_received == 0:
            return 0.0
        elapsed_hours = (self._clock() - first).total_seconds() / 3600
        if elapsed_hours < 1 / 60:
            return 0.0
        return metrics.total_cargo_received / elapsed_hours

    def _duplicate_rate(self, source_id: str, metrics: SourceMetrics) -> float:
        """Доля дублей (данные пайплайна через инжектированный провайдер)."""
        if self._duplicates_provider is None or metrics.total_cargo_received == 0:
            return 0.0
        duplicates = self._duplicates_provider(source_id)
        return duplicates / metrics.total_cargo_received

    async def _record_history(
        self, spec: SourceSpec, trace: str, *, severity: Severity, title: str, details: str
    ) -> None:
        entry = HistoryEntry.create(
            kind=HistoryKind.SOURCE_EVENT,
            severity=severity,
            title=title,
            details=details,
            source=_SOURCE,
            trace_id=trace,
        )
        try:
            await self._history.add(entry)
        except StorageError:
            logger.exception("Не удалось записать опрос источника в журнал")

    async def _notify_failure(
        self, spec: SourceSpec, trace: str, error: str, attempts: int
    ) -> None:
        await self._send_notification(
            title=f"Источник «{spec.name}»: не удалось получить грузы",
            body=f"{error}\nПопытка {attempts}/{spec.retry_policy.max_attempts}",
            spec=spec,
            trace=trace,
        )

    async def _notify_recovered(self, spec: SourceSpec, trace: str) -> None:
        notification = (
            NotificationBuilder()
            .title(f"🟢 Источник «{spec.name}» восстановлен")
            .body("Опрос снова успешен — грузы поступают.")
            .severity(Severity.SUCCESS)
            .category(NotificationCategory.MONITOR)
            .source(_SOURCE)
            .module(spec.id)
            .trace_id(trace)
            .build()
        )
        try:
            await self._notifications.send(notification)
        except Exception:
            logger.exception("Не удалось отправить уведомление о восстановлении")

    async def _notify_rate_limited(self, spec: SourceSpec, trace: str, waited: float) -> None:
        await self._send_notification(
            title=f"Источник «{spec.name}»: превышен лимит запросов",
            body=f"Опрос задержан на {waited:.0f} с — проверьте интервал опроса.",
            spec=spec,
            trace=trace,
        )

    async def _notify_ati_token_expiring(self, spec: SourceSpec, trace: str) -> None:
        if not self._cooldown.should_send(f"source-token-expiring:{spec.id}"):
            return
        await self._send_notification(
            title="⚠️ Токен ATI истекает через 24 часа",
            body="Обновите временный access_token ATI в настройках.",
            spec=spec,
            trace=trace,
        )

    async def _notify_ati_token_expired(self, spec: SourceSpec, trace: str) -> None:
        if not self._cooldown.should_send(f"source-token-expired:{spec.id}"):
            return
        await self._send_notification(
            title="🔴 Токен ATI истёк",
            body="Обновите токен в настройках. ATI polling остановлен до обновления.",
            spec=spec,
            trace=trace,
        )

    async def _send_notification(
        self, *, title: str, body: str, spec: SourceSpec, trace: str
    ) -> None:
        notification = (
            NotificationBuilder()
            .title(title)
            .body(body)
            .severity(Severity.WARNING)
            .category(NotificationCategory.MONITOR)
            .source(_SOURCE)
            .module(spec.id)
            .trace_id(trace)
            .build()
        )
        try:
            await self._notifications.send(notification)
        except Exception:
            logger.exception("Не удалось отправить уведомление источника")


class SourcePollJob:
    """Job-адаптер: Scheduler запускает опрос источника по его расписанию.

    Таймаут и ретраи применяет SourceRuntime по политикам из SourceSpec —
    у job намеренно нет собственных (не дублировать политики).
    """

    def __init__(
        self, runtime: SourceRuntime, spec: SourceSpec, schedule: JobSchedule | None = None
    ) -> None:
        self._runtime = runtime
        self._source_id = spec.id
        self._spec = JobSpec(
            name=f"source:{spec.id}",
            schedule=schedule if schedule is not None else spec.schedule,
            timeout_seconds=None,
            retry=JobRetryPolicy(),
            max_parallel_runs=1,
        )

    @property
    def spec(self) -> JobSpec:
        """Описание job для Scheduler."""
        return self._spec

    async def run(self, context: JobContext) -> None:
        """Опросить источник (trace_id запуска job идёт насквозь)."""
        await self._runtime.run_source(self._source_id, trace_id=context.trace_id)
