"""IntelligentMatchingService — итоговый выбор лучшего груза с объяснением.

Stage 8.5: final_score = 30% совместимость + 30% прибыль + 20% эффективность
маршрута + 10% предпочтения + 10% свежесть (веса — MatchingWeights из
настроек). Маршрут и холостой подгон считает RouteService (провайдер за
портом), экономику — CargoProfitCalculator; каждое решение фиксируется
MatchingDecision и событиями (RouteCalculated, ProfitCalculated,
MatchingDecisionCreated). Сервис не знает ни карт, ни Telegram, ни SQLite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.clock import utc_now
from app.core.events import (
    BestCargoSelected,
    CargoRejectedByPreference,
    MatchingDecisionCreated,
    ProfitCalculated,
)
from app.core.models.matching import (
    IntelligentCargoMatch,
    MatchingContext,
    MatchingDecision,
    MatchingWeights,
    ProfitAnalysis,
)
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.scoring import freshness_score
from app.core.models.search import CargoMatch
from app.core.models.severity import Severity
from app.core.ports import EventPublisher, NotificationSender
from app.services.matching.preference_engine import PreferenceEngine
from app.services.matching.profit_calculator import CargoProfitCalculator
from app.services.matching.route_score import RouteScoreCalculator
from app.services.routes import RouteService

logger = logging.getLogger(__name__)

_SOURCE = "matching"
# Прибыль/км для 100 баллов компонента прибыли (v1, калибруется на живых данных).
_EXCELLENT_PROFIT_PER_KM = Decimal(120)


def _money(value: Decimal) -> str:
    """120000 → «120 000» (узкие группы разрядов для уведомлений)."""
    return f"{value:,.0f}".replace(",", " ")


class IntelligentMatchingService:
    """Интеллектуальный слой над результатами Search Engine."""

    def __init__(
        self,
        *,
        preferences: PreferenceEngine,
        profit: CargoProfitCalculator,
        routes: RouteService,
        route_score: RouteScoreCalculator,
        event_bus: EventPublisher,
        notifications: NotificationSender,
        weights: MatchingWeights | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._preferences = preferences
        self._profit = profit
        self._routes = routes
        self._route_score = route_score
        self._events = event_bus
        self._notifications = notifications
        self._weights = weights if weights is not None else MatchingWeights()
        self._clock = clock

    async def rank(
        self,
        matches: Sequence[CargoMatch],
        context: MatchingContext,
        *,
        trace_id: str = "",
    ) -> tuple[IntelligentCargoMatch, ...]:
        """Оценить совместимые грузы и отсортировать по final_score."""
        trace = trace_id if trace_id else uuid4().hex
        driver = context.driver_profile
        evaluated: list[IntelligentCargoMatch] = []
        for match in matches:
            if not match.compatible:
                continue
            verdict = self._preferences.evaluate(match, driver)
            if verdict.rejected:
                self._record(
                    match,
                    0,
                    selected=False,
                    reason=verdict.rejected_reason,
                    trace=trace,
                    driver_id=driver.id,
                )
                self._events.publish(
                    CargoRejectedByPreference(
                        cargo_id=match.cargo_id,
                        driver_id=driver.id,
                        reason=verdict.rejected_reason,
                        trace_id=trace,
                    )
                )
                continue
            evaluated.append(
                await self._evaluate(match, context, verdict.score, verdict.notes, trace)
            )
        return tuple(
            sorted(
                evaluated,
                key=lambda m: (
                    -m.final_score,
                    -(m.profit.net_profit if m.profit is not None else Decimal(0)),
                ),
            )
        )

    async def select_best(
        self,
        matches: Sequence[CargoMatch],
        context: MatchingContext,
        *,
        trace_id: str = "",
    ) -> IntelligentCargoMatch | None:
        """Лучший груз с решением и событием (уведомление шлёт notify_best)."""
        trace = trace_id if trace_id else uuid4().hex
        ranked = await self.rank(matches, context, trace_id=trace)
        return self.select_from_ranked(ranked, context, trace_id=trace)

    def select_from_ranked(
        self,
        ranked: Sequence[IntelligentCargoMatch],
        context: MatchingContext,
        *,
        trace_id: str,
    ) -> IntelligentCargoMatch | None:
        """Выбрать лучшего из УЖЕ оценённых (без повторной оценки).

        Пайплайн (Stage 9.5) зовёт rank один раз и затем этот метод —
        события ProfitCalculated/RouteCalculated не дублируются.
        """
        if not ranked:
            return None
        best = ranked[0]
        cargo = best.cargo_match.cargo
        route = " → ".join(p for p in (cargo.loading_region, cargo.unloading_region) if p)
        trace = trace_id
        self._record(
            best.cargo_match,
            best.final_score,
            selected=True,
            reason="",
            trace=trace,
            driver_id=context.driver_profile.id,
            profit=best.profit.net_profit if best.profit is not None else None,
            explanation=best.explanation,
            route=route,
            distance_km=(
                best.route_estimate.distance_km if best.route_estimate is not None else None
            ),
        )
        self._events.publish(
            BestCargoSelected(
                cargo_id=best.cargo_match.cargo_id,
                driver_id=context.driver_profile.id,
                final_score=best.final_score,
                trace_id=trace,
            )
        )
        return best

    async def notify_best(self, best: IntelligentCargoMatch, trace_id: str = "") -> None:
        """Уведомить о лучшем грузе (категория ROUTE: экономика рейса)."""
        cargo = best.cargo_match.cargo
        route = " → ".join(p for p in (cargo.loading_region, cargo.unloading_region) if p)
        lines = [route if route else "Маршрут не указан"]
        distance_km = (
            best.route_estimate.distance_km
            if best.route_estimate is not None
            else cargo.distance_km
        )
        if distance_km is not None and distance_km > 0:
            lines.append(f"Расстояние: {round(distance_km)} км")
        profit = best.profit
        if profit is not None:
            lines.append(f"Доход: {_money(profit.gross_profit)} ₽")
            lines.append(f"Расходы: {_money(profit.expenses)} ₽")
            lines.append(f"Чистая прибыль: {_money(profit.net_profit)} ₽")
            if profit.profit_per_km is not None:
                lines.append(f"Прибыль: {round(profit.profit_per_km)} ₽/км")
        lines.append(f"Совместимость: {best.cargo_match.compatibility_result.score}%")
        lines.append("Почему:")
        lines.extend(f"✅ {reason}" for reason in best.explanation)

        builder = (
            NotificationBuilder()
            .title("🚚 Лучший груз найден")
            .body("\n".join(lines))
            .severity(Severity.SUCCESS)
            .category(NotificationCategory.ROUTE)
            .source(_SOURCE)
            .payload_item("cargo_id", cargo.id)
            .payload_item("route", route)
            .payload_item("ai_score", str(best.final_score))
            .trace_id(trace_id)
        )
        if profit is not None:
            builder.payload_item("profit", str(profit.net_profit))
        if cargo.url:
            builder.action("Открыть ATI", cargo.url)
        # Callback-кнопки Telegram (id из whitelist бота; cargo_id — в payload).
        builder.action("Подробнее", action_id="details")
        builder.action("Игнорировать", action_id="ignore")
        try:
            await self._notifications.send(builder.build())
        except Exception:
            logger.exception("Не удалось отправить уведомление о лучшем грузе")

    # ── Внутреннее ────────────────────────────────────────────────────────────

    async def _evaluate(
        self,
        match: CargoMatch,
        context: MatchingContext,
        preference_score: int,
        preference_notes: tuple[str, ...],
        trace: str,
    ) -> IntelligentCargoMatch:
        cargo = match.cargo
        estimate = context.route_estimate
        if estimate is None:
            estimate = await self._routes.estimate_for_cargo(cargo, trace_id=trace)

        empty_run_cost = Decimal(0)
        location = context.current_location
        if location and cargo.loading_region and location != cargo.loading_region:
            empty_run_cost = await self._routes.empty_run_cost(
                location, cargo.loading_region, trace_id=trace
            )

        profit = self._profit.analyze(cargo, estimate, empty_run_cost=empty_run_cost)
        if profit is not None:
            self._events.publish(
                ProfitCalculated(cargo_id=cargo.id, analysis=profit, trace_id=trace)
            )
        profit_score = self._profit_score(profit)

        cargo_context = replace(context, route_estimate=estimate)
        route_score, route_notes = self._route_score.score(cargo, cargo_context)
        freshness = round(freshness_score(cargo.created_at, self._clock()))

        weights = self._weights
        final = round(
            match.compatibility_result.score * weights.compatibility
            + profit_score * weights.profit
            + route_score * weights.route
            + preference_score * weights.preferences
            + freshness * weights.freshness
        )
        explanation: list[str] = []
        if match.compatibility_result.score >= 90:
            explanation.append("Идеальная совместимость транспорта")
        elif match.compatible:
            explanation.append("Подходит по машине")
        if profit is not None and profit.net_profit > 0:
            profit_line = f"Прибыль {profit.net_profit:.0f} ₽"
            if profit.profit_per_km is not None:
                profit_line += f" · {round(profit.profit_per_km)} ₽/км"
            explanation.append(profit_line)
        elif profit is not None:
            explanation.append(f"Убыточный груз: {profit.net_profit:.0f} ₽")
        if empty_run_cost > 0:
            explanation.append(f"Холостой подгон обойдётся в {_money(empty_run_cost)} ₽")
        explanation.extend(preference_notes)
        explanation.extend(route_notes)

        return IntelligentCargoMatch(
            cargo_match=match,
            final_score=max(0, min(100, final)),
            preference_score=preference_score,
            profit_score=profit_score,
            route_score=route_score,
            freshness_score=freshness,
            profit=profit,
            route_estimate=estimate,
            explanation=tuple(explanation),
        )

    @staticmethod
    def _profit_score(profit: ProfitAnalysis | None) -> int:
        if profit is None:
            return 50  # нет данных — нейтрально
        if profit.net_profit <= 0 or profit.profit_per_km is None:
            return 0
        ratio = profit.profit_per_km / _EXCELLENT_PROFIT_PER_KM * 100
        return int(min(Decimal(100), ratio))

    def _record(
        self,
        match: CargoMatch,
        score: int,
        *,
        selected: bool,
        reason: str,
        trace: str,
        driver_id: str,
        profit: Decimal | None = None,
        explanation: tuple[str, ...] = (),
        route: str = "",
        distance_km: float | None = None,
    ) -> None:
        decision = MatchingDecision.create(
            cargo_id=match.cargo_id,
            driver_id=driver_id,
            score=score,
            selected=selected,
            rejected_reason=reason,
            vehicle_profile_id=match.vehicle_profile_id,
            profit=profit,
            explanation=explanation,
            route=route,
            distance_km=distance_km,
            trace_id=trace,
        )
        self._events.publish(MatchingDecisionCreated(decision=decision))
