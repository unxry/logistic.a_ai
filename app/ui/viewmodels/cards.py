"""Карточные ViewModel — готовые к отрисовке данные (Stage 8.6).

Каждая карточка — неизменяемый dataclass со строками для отображения и
числами для индикаторов (score, проценты). Фабрики ``from_*`` переводят
модели ядра в презентационную форму; UI-агент работает только с этими
типами и не касается доменной логики.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Self

from app.core.models.analytics import MatchingAnalytics
from app.core.models.connection import ConnectionState
from app.core.models.history import HistoryEntry
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile
from app.core.models.matching import IntelligentCargoMatch
from app.core.models.notification_history import NotificationHistoryEntry
from app.core.models.sources import SourceHealth, SourceStatus
from app.ui.viewmodels.formatting import (
    EMPTY,
    dimensions_cm,
    distance_km,
    group_digits,
    money,
    rate_per_km,
    relative_time,
    volume_m3,
    weight_kg,
)

_BODY_TYPE_LABELS: dict[BodyType, str] = {
    BodyType.TENT: "Тент",
    BodyType.REFRIGERATOR: "Рефрижератор",
    BodyType.ISOTHERMAL: "Изотерм",
    BodyType.BOX: "Фургон",
    BodyType.FLATBED: "Бортовой",
    BodyType.CONTAINER: "Контейнеровоз",
    BodyType.OTHER: "Другой кузов",
}


class BadgeTone(Enum):
    """Тон статуса — UI выбирает цвет/иконку, не зная домена."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    MUTED = "muted"


@dataclass(frozen=True, slots=True)
class StatusBadge:
    """Статус со светофорным тоном и человекочитаемой подписью."""

    tone: BadgeTone
    label: str
    detail: str = ""


def telegram_status_badge(state: ConnectionState, detail: str = "") -> StatusBadge:
    """Состояние Telegram → бейдж."""
    mapping = {
        ConnectionState.CONNECTED: (BadgeTone.OK, "Подключён"),
        ConnectionState.CONNECTING: (BadgeTone.MUTED, "Подключение…"),
        ConnectionState.DISCONNECTED: (BadgeTone.MUTED, "Не подключён"),
        ConnectionState.ERROR: (BadgeTone.ERROR, "Ошибка"),
    }
    tone, label = mapping[state]
    return StatusBadge(tone=tone, label=label, detail=detail)


def source_status_badge(status: SourceStatus) -> StatusBadge:
    """Здоровье источника → бейдж."""
    mapping = {
        SourceStatus.ONLINE: (BadgeTone.OK, "В сети"),
        SourceStatus.DEGRADED: (BadgeTone.WARNING, "Сбоит"),
        SourceStatus.FAILED: (BadgeTone.ERROR, "Недоступен"),
        SourceStatus.DISABLED: (BadgeTone.MUTED, "Выключен"),
    }
    tone, label = mapping[status]
    return StatusBadge(tone=tone, label=label)


@dataclass(frozen=True, slots=True)
class ActionViewModel:
    """Действие карточки («Открыть объявление» и т. п.)."""

    id: str
    label: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class CargoCardViewModel:
    """Карточка груза для дашборда и списка рекомендаций."""

    cargo_id: str
    route: str
    distance: str
    weight: str
    dimensions: str
    price: str
    profit: str
    profit_per_km: str
    score: int
    compatibility: int
    explanation: tuple[str, ...] = ()
    actions: tuple[ActionViewModel, ...] = ()
    workflow_state: str = "Новый"

    @classmethod
    def from_match(cls, match: IntelligentCargoMatch) -> Self:
        """Построить карточку из результата интеллектуального подбора."""
        cargo = match.cargo_match.cargo
        route = " → ".join(p for p in (cargo.loading_region, cargo.unloading_region) if p)
        card_distance = (
            match.route_estimate.distance_km
            if match.route_estimate is not None
            else cargo.distance_km
        )
        profit = match.profit
        actions: tuple[ActionViewModel, ...] = ()
        if cargo.url:
            actions = (ActionViewModel(id="open", label="Открыть объявление", url=cargo.url),)
        return cls(
            cargo_id=cargo.id,
            route=route if route else EMPTY,
            distance=distance_km(card_distance),
            weight=weight_kg(cargo.weight_kg),
            dimensions=dimensions_cm(cargo.length_cm, cargo.width_cm, cargo.height_cm),
            price=money(cargo.payment_amount) if cargo.payment_amount is not None else EMPTY,
            profit=money(profit.net_profit) if profit is not None else EMPTY,
            profit_per_km=(
                rate_per_km(profit.profit_per_km)
                if profit is not None and profit.profit_per_km is not None
                else ""
            ),
            score=match.final_score,
            compatibility=match.cargo_match.compatibility_result.score,
            explanation=match.explanation,
            actions=actions,
        )

    @classmethod
    def from_cargo(cls, cargo: Cargo, *, workflow_state: str = "Новый") -> Self:
        """Построить карточку из сохранённого груза без пересчёта AI."""
        route = " → ".join(p for p in (cargo.loading_region, cargo.unloading_region) if p)
        actions: tuple[ActionViewModel, ...] = ()
        if cargo.url:
            actions = (ActionViewModel(id="open", label="Открыть объявление", url=cargo.url),)
        return cls(
            cargo_id=cargo.id,
            route=route if route else EMPTY,
            distance=distance_km(cargo.distance_km),
            weight=weight_kg(cargo.weight_kg),
            dimensions=dimensions_cm(cargo.length_cm, cargo.width_cm, cargo.height_cm),
            price=money(cargo.payment_amount) if cargo.payment_amount is not None else EMPTY,
            profit=EMPTY,
            profit_per_km="",
            score=0,
            compatibility=0,
            explanation=("Сохранённый груз из локальной базы",),
            actions=actions,
            workflow_state=workflow_state,
        )


@dataclass(frozen=True, slots=True)
class SourceStatusViewModel:
    """Карточка источника грузов.

    Stage 9.6: ``throughput`` («12 грузов/ч») и ``reliability``
    («отклик 850 мс · ошибки 8% · дубли 20%») — production-метрики
    источника, готовые к отрисовке.
    """

    id: str
    name: str
    status: StatusBadge
    last_sync: str
    cargo_count: int
    errors: str = ""
    consecutive_failures: int = 0
    throughput: str = ""
    reliability: str = ""

    @classmethod
    def from_health(
        cls,
        source_id: str,
        name: str,
        health: SourceHealth,
        *,
        cargo_count: int,
        now: datetime,
    ) -> Self:
        """Построить карточку из здоровья источника."""
        last_sync = (
            relative_time(health.last_success, now)
            if health.last_success is not None
            else "ещё не синхронизировался"
        )
        throughput = f"{health.cargos_per_hour:.0f} грузов/ч" if health.cargos_per_hour > 0 else ""
        reliability_parts: list[str] = []
        if health.average_duration_ms > 0:
            reliability_parts.append(f"отклик {health.average_duration_ms:.0f} мс")
        if health.error_rate > 0:
            reliability_parts.append(f"ошибки {health.error_rate:.0%}")
        if health.duplicate_rate > 0:
            reliability_parts.append(f"дубли {health.duplicate_rate:.0%}")
        return cls(
            id=source_id,
            name=name,
            status=source_status_badge(health.status),
            last_sync=last_sync,
            cargo_count=cargo_count,
            errors=health.last_error if health.last_error is not None else "",
            consecutive_failures=health.consecutive_failures,
            throughput=throughput,
            reliability=" · ".join(reliability_parts),
        )


@dataclass(frozen=True, slots=True)
class AnalyticsViewModel:
    """Сводка аналитики для дашборда."""

    today_found: int
    matched_count: int
    potential_profit: str
    best_route: str
    average_profit: str
    rejected_count: int = 0
    average_score: str = "—"
    total_profit: str = "—"

    @classmethod
    def build(
        cls,
        *,
        found_count: int,
        statistics: MatchingAnalytics,
        potential_profit: Decimal | None = None,
    ) -> Self:
        """Собрать сводку из счётчиков и статистики подбора."""
        return cls(
            today_found=found_count,
            matched_count=statistics.compatible_count,
            potential_profit=money(potential_profit) if potential_profit is not None else EMPTY,
            best_route=statistics.best_routes[0] if statistics.best_routes else EMPTY,
            average_profit=(
                money(statistics.average_profit) if statistics.average_profit > 0 else EMPTY
            ),
            rejected_count=statistics.rejected_count,
            average_score=f"{statistics.average_score:.1f}"
            if statistics.average_score > 0
            else EMPTY,
            total_profit=money(potential_profit) if potential_profit is not None else EMPTY,
        )

    @classmethod
    def empty(cls) -> Self:
        """Пустая сводка (до первого обновления)."""
        return cls.build(found_count=0, statistics=MatchingAnalytics())


@dataclass(frozen=True, slots=True)
class VehicleViewModel:
    """Карточка активного транспорта."""

    id: str
    name: str
    summary: str
    dimensions: str

    @classmethod
    def from_profile(cls, profile: VehicleProfile) -> Self:
        """Построить карточку из профиля транспорта."""
        body = _BODY_TYPE_LABELS.get(profile.body_type, profile.body_type.value)
        summary = (
            f"{body} · {group_digits(profile.cargo_capacity_kg)} кг"
            f" · {volume_m3(profile.volume_m3)} · {profile.pallet_capacity} паллет"
        )
        return cls(
            id=profile.id,
            name=profile.name,
            summary=summary,
            dimensions=dimensions_cm(profile.length_cm, profile.width_cm, profile.height_cm),
        )


@dataclass(frozen=True, slots=True)
class EventRowViewModel:
    """Строка журнала «последние события»."""

    title: str
    time_label: str
    severity: str
    kind: str
    source: str = ""
    details: str = ""

    @classmethod
    def from_entry(cls, entry: HistoryEntry, *, now: datetime) -> Self:
        """Построить строку из записи журнала."""
        return cls(
            title=entry.title,
            time_label=relative_time(entry.occurred_at, now),
            severity=entry.severity.value,
            kind=entry.kind.value,
            source=entry.source,
            details=entry.details,
        )

    @classmethod
    def from_notification(cls, entry: NotificationHistoryEntry, *, now: datetime) -> Self:
        """Построить строку Timeline из истории уведомлений."""
        route = entry.route if entry.route else "Маршрут не указан"
        score = f" · AI {entry.ai_score}" if entry.ai_score is not None else ""
        opened = "Открыто" if entry.open_state.value == "opened" else "Не открыто"
        return cls(
            title=f"{route}{score}",
            time_label=relative_time(entry.occurred_at, now),
            severity="success" if entry.ai_score is not None else "info",
            kind=entry.type,
            source=entry.source,
            details=opened,
        )


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """Полное состояние дашборда одним значением (для события и тестов)."""

    application_status: StatusBadge
    telegram_status: StatusBadge
    sources_status: tuple[SourceStatusViewModel, ...]
    active_vehicle: VehicleViewModel | None
    best_matches: tuple[CargoCardViewModel, ...]
    analytics_summary: AnalyticsViewModel
    recent_events: tuple[EventRowViewModel, ...]
    favorite_matches: tuple[CargoCardViewModel, ...] = ()
    notification_events: tuple[EventRowViewModel, ...] = ()
