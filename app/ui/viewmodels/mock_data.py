"""MockDashboardDataProvider — красивые детерминированные данные без домена.

Для агента, который будет строить macOS UI: полный дашборд (источники,
аналитика, журнал, транспорт) и готовые карточки рекомендаций — без ATI,
SQLite и подбора. Все времена отсчитываются от фиксированного ``now``,
идентификаторы фиксированы — снапшот-тесты воспроизводимы байт в байт.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.models.analytics import MatchingAnalytics
from app.core.models.connection import ConnectionState
from app.core.models.history import HistoryEntry, HistoryKind
from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.notification_history import (
    NotificationHistoryEntry,
    NotificationOpenState,
)
from app.core.models.severity import Severity
from app.core.models.sources import SourceHealth, SourceStatus
from app.ui.viewmodels.cards import ActionViewModel, CargoCardViewModel

#: Фиксированный «сейчас» мок-данных (детерминизм снапшотов).
MOCK_NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

#: Потенциальная прибыль трёх мок-рекомендаций (85 000 + 49 610 + 26 000).
MOCK_POTENTIAL_PROFIT = Decimal(160610)


def mock_vehicle(now: datetime = MOCK_NOW) -> VehicleProfile:
    """Эталонный MAN TGL из сценариев ТЗ (фиксированный id)."""
    return VehicleProfile(
        id="vehicle-man-tgl",
        name="MAN TGL",
        vehicle_type=VehicleType.TRUCK,
        body_type=BodyType.TENT,
        cargo_capacity_kg=6000,
        length_cm=620,
        width_cm=245,
        height_cm=250,
        volume_m3=38.0,
        pallet_capacity=14,
        created_at=now,
        updated_at=now,
    )


def mock_best_matches() -> tuple[CargoCardViewModel, ...]:
    """Три готовые карточки рекомендаций (лучшая — эталон ТЗ 85 000 ₽)."""
    return (
        CargoCardViewModel(
            cargo_id="cargo-spb",
            route="Москва → Санкт-Петербург",
            distance="710 км",
            weight="5 000 кг",
            dimensions="500 × 200 × 220 см",
            price="120 000 ₽",
            profit="85 000 ₽",
            profit_per_km="120 ₽/км",
            score=98,
            compatibility=100,
            explanation=(
                "Идеальная совместимость транспорта",
                "Прибыль 85000 ₽ · 120 ₽/км",
                "Ваше направление: Санкт-Петербург",
                "Минимальный холостой пробег: загрузка в домашнем регионе",
                "Быстрая магистральная трасса",
            ),
            actions=(
                ActionViewModel(
                    id="open", label="Открыть объявление", url="https://ati.su/cargo/demo-1"
                ),
            ),
        ),
        CargoCardViewModel(
            cargo_id="cargo-kazan",
            route="Москва → Казань",
            distance="820 км",
            weight="5 500 кг",
            dimensions="480 × 200 × 210 см",
            price="90 000 ₽",
            profit="49 610 ₽",
            profit_per_km="61 ₽/км",
            score=80,
            compatibility=95,
            explanation=(
                "Подходит по машине",
                "Прибыль 49610 ₽ · 61 ₽/км",
                "Минимальный холостой пробег: загрузка в домашнем регионе",
            ),
            actions=(
                ActionViewModel(
                    id="open", label="Открыть объявление", url="https://ati.su/cargo/demo-2"
                ),
            ),
        ),
        CargoCardViewModel(
            cargo_id="cargo-tver",
            route="Москва → Тверь",
            distance="170 км",
            weight="2 400 кг",
            dimensions="—",
            price="35 000 ₽",
            profit="26 000 ₽",
            profit_per_km="153 ₽/км",
            score=76,
            compatibility=85,
            explanation=(
                "Подходит по машине",
                "Прибыль 26000 ₽ · 153 ₽/км",
                "Комфортное плечо",
            ),
            actions=(),
        ),
    )


class MockDashboardDataProvider:
    """Реализация порта DashboardDataProvider на фиксированных данных."""

    def __init__(self, now: datetime = MOCK_NOW) -> None:
        self._now = now

    def telegram_state(self) -> ConnectionState:
        """Telegram «подключён» — счастливый путь для вёрстки."""
        return ConnectionState.CONNECTED

    def active_vehicle(self) -> VehicleProfile | None:
        """Активный транспорт — эталонный MAN TGL."""
        return mock_vehicle(self._now)

    def sources_health(self) -> Mapping[str, SourceHealth]:
        """Три источника: живой, упавший и выключенный (все состояния UI)."""
        return {
            "ati": SourceHealth(
                status=SourceStatus.ONLINE,
                last_success=self._now - timedelta(minutes=5),
                success_rate=0.98,
                average_duration_ms=850.0,
                items_received=542,
                last_received_count=17,
                last_success_duration_ms=820,
                cargos_per_hour=68.0,
                duplicate_rate=0.21,
                error_rate=0.02,
            ),
            "ozon": SourceHealth(
                status=SourceStatus.FAILED,
                last_success=self._now - timedelta(minutes=42),
                last_error="HTTP 503: сервис временно недоступен",
                last_error_at=self._now - timedelta(minutes=3),
                consecutive_failures=4,
                success_rate=0.61,
                average_duration_ms=2140.0,
                items_received=87,
                cargos_per_hour=11.0,
                duplicate_rate=0.05,
                error_rate=0.39,
            ),
            "csv": SourceHealth(status=SourceStatus.DISABLED),
        }

    def source_names(self) -> Mapping[str, str]:
        """Человекочитаемые имена источников."""
        return {"ati": "ATI.SU", "ozon": "Ozon Логистика", "csv": "CSV-импорт"}

    def cargo_counts(self) -> Mapping[str, int]:
        """Грузов получено от каждого источника."""
        return {"ati": 542, "ozon": 87, "csv": 12}

    async def matching_statistics(self) -> MatchingAnalytics:
        """Статистика подбора как после насыщенного дня."""
        return MatchingAnalytics(
            total_matches=641,
            compatible_count=38,
            rejected_count=17,
            average_score=74.2,
            average_profit=Decimal(82500),
            best_routes=("Москва → Санкт-Петербург", "Москва → Казань"),
            rejection_reasons={"Перегруз": 9, "Запрещённый регион «Сочи»": 5, "Не тот кузов": 3},
        )

    async def recent_events(self, limit: int) -> Sequence[HistoryEntry]:
        """Последние события журнала (новые первыми)."""
        entries = (
            HistoryEntry(
                id="event-best-cargo",
                occurred_at=self._now - timedelta(minutes=4),
                kind=HistoryKind.NOTIFICATION,
                severity=Severity.SUCCESS,
                title="🚚 Лучший груз найден",
                details="Москва → Санкт-Петербург · чистая прибыль 85 000 ₽",
                source="matching",
                trace_id="mock-trace-best",
            ),
            HistoryEntry(
                id="event-ati-sync",
                occurred_at=self._now - timedelta(minutes=5),
                kind=HistoryKind.SOURCE_EVENT,
                severity=Severity.INFO,
                title="ATI.SU: получено 17 новых грузов",
                source="ati",
                trace_id="mock-trace-sync",
            ),
            HistoryEntry(
                id="event-ozon-down",
                occurred_at=self._now - timedelta(minutes=42),
                kind=HistoryKind.ERROR,
                severity=Severity.WARNING,
                title="⚠️ Ozon Логистика недоступен",
                details="HTTP 503: сервис временно недоступен",
                source="ozon",
                trace_id="mock-trace-ozon",
            ),
            HistoryEntry(
                id="event-app-started",
                occurred_at=self._now - timedelta(hours=3),
                kind=HistoryKind.SYSTEM_EVENT,
                severity=Severity.INFO,
                title="LogistAI запущен",
                source="app",
            ),
        )
        return entries[:limit]

    async def favorite_cargos(self, limit: int) -> Sequence[Cargo]:
        """Избранное в мок-режиме строится из готовых рекомендаций."""
        cargos = tuple(
            Cargo(
                id=card.cargo_id,
                source_id="ati",
                title=card.route,
                loading_region=card.route.partition(" → ")[0],
                unloading_region=card.route.partition(" → ")[2],
                url=card.actions[0].url if card.actions else "",
                created_at=self._now - timedelta(minutes=11),
            )
            for card in mock_best_matches()[:2]
        )
        return cargos[:limit]

    async def notification_history(self, limit: int) -> Sequence[NotificationHistoryEntry]:
        """Демо-история уведомлений для Timeline."""
        entries = (
            NotificationHistoryEntry(
                id="nh-best",
                notification_id="notification-best",
                occurred_at=self._now - timedelta(minutes=4),
                type="route",
                source="matching",
                route="Москва → Санкт-Петербург",
                profit=Decimal(85000),
                ai_score=98,
                open_state=NotificationOpenState.OPENED,
                cargo_id="cargo-spb",
                trace_id="mock-trace-best",
            ),
            NotificationHistoryEntry(
                id="nh-kazan",
                notification_id="notification-kazan",
                occurred_at=self._now - timedelta(minutes=19),
                type="route",
                source="matching",
                route="Москва → Казань",
                profit=Decimal(49610),
                ai_score=80,
                cargo_id="cargo-kazan",
                trace_id="mock-trace-kazan",
            ),
        )
        return entries[:limit]
