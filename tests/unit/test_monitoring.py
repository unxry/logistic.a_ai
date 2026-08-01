"""Тесты Monitoring & Analytics: хранилище решений, счётчики, монитор, отчёт."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.buses import EventBus
from app.core.clock import utc_now
from app.core.events import (
    CargoMatched,
    CargoReceived,
    CargoRejected,
    JobFailed,
    MatchingDecisionCreated,
    SourceCompleted,
    SourceFailed,
)
from app.core.models.analytics import summarize_decisions
from app.core.models.logistics.cargo import Cargo
from app.core.models.matching import MatchingDecision
from app.core.models.notification import Notification
from app.core.models.scheduler import JobContext, JobResult
from app.core.models.settings import AppSettings
from app.core.models.sources import SourceHealth, SourceStatus
from app.infrastructure.storage.database import Database
from app.infrastructure.storage.matching_repository import SqliteMatchingRepository
from app.services.monitoring import (
    AnalyticsCollector,
    DailyAnalyticsReportJob,
    DecisionPersister,
    MatchingQualityService,
    SourceHealthMonitor,
)


class _Sender:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


def _decision(**overrides: object) -> MatchingDecision:
    params: dict[str, object] = {
        "cargo_id": "c1",
        "driver_id": "d1",
        "score": 90,
        "selected": True,
        "profit": Decimal(85000),
        "explanation": ("Идеальная совместимость", "Прибыль 85000 ₽"),
        "route": "Москва → Санкт-Петербург",
        "trace_id": "t-1",
        "vehicle_profile_id": "v1",
    }
    params.update(overrides)
    return MatchingDecision.create(**params)  # type: ignore[arg-type]


def _repo(tmp_path: Path) -> SqliteMatchingRepository:
    database = Database(tmp_path / "m.db")
    database.connect()
    return SqliteMatchingRepository(database)


# ── Decision Storage (SQLite) ────────────────────────────────────────────────


async def test_decision_roundtrip_with_trace(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    decision = _decision()
    await repo.save_decision(decision)

    loaded = await repo.get_history()
    assert len(loaded) == 1
    assert loaded[0] == decision  # trace_id, profit, explanation, route — сквозные


async def test_history_filters_by_driver(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.save_decision(_decision(driver_id="d1"))
    await repo.save_decision(_decision(driver_id="d2"))

    assert len(await repo.get_history(driver_id="d1")) == 1
    assert len(await repo.get_history()) == 2


async def test_statistics_and_driver_metrics(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.save_decision(_decision(score=90, profit=Decimal(80000)))
    await repo.save_decision(_decision(score=70, profit=Decimal(60000)))
    await repo.save_decision(
        _decision(selected=False, score=0, profit=None, rejected_reason="Перегруз")
    )

    stats = await repo.get_statistics()
    assert stats.total_matches == 3
    assert stats.compatible_count == 2 and stats.rejected_count == 1
    assert stats.average_profit == Decimal(70000)
    assert stats.best_routes[0] == "Москва → Санкт-Петербург"
    assert stats.rejection_reasons == {"Перегруз": 1}

    driver = await repo.driver_statistics("d1")
    assert driver.searched_count == 3 and driver.selected_count == 2
    assert driver.estimated_income == Decimal(140000)
    assert driver.average_match_score > 50


def test_quality_service_summarize_empty_and_full() -> None:
    assert MatchingQualityService().summarize(()).total_matches == 0
    stats = summarize_decisions([_decision(), _decision(selected=False, score=0)])
    assert stats.total_matches == 2 and stats.compatible_count == 1


# ── Collector: события → счётчики ────────────────────────────────────────────


def test_collector_updates_from_events() -> None:
    bus = EventBus()
    collector = AnalyticsCollector()
    collector.attach(bus)

    cargo = Cargo(id="c1", source_id="ati")
    bus.publish(CargoReceived(source_id="ati", trace_id="t", items=(cargo, cargo)))
    bus.publish(SourceCompleted(source_id="ati", trace_id="t", items_count=2, duration_ms=5))
    bus.publish(SourceFailed(source_id="ozon", trace_id="t", error="сеть"))
    bus.publish(CargoMatched(cargo_id="c1", vehicle_profile_id="v", score=90, trace_id="t"))
    bus.publish(
        CargoRejected(cargo_id="c2", vehicle_profile_id="v", reasons=("вес",), trace_id="t")
    )
    result = JobResult(
        job_name="j",
        success=False,
        started_at=utc_now(),
        finished_at=utc_now(),
        duration_ms=1,
        trace_id="t",
    )
    bus.publish(JobFailed(result=result))

    assert collector.total_cargo_received() == 2
    assert collector.source_runs["ati"] == 1
    assert collector.source_failures["ozon"] == 1
    assert collector.matched_count == 1 and collector.rejected_count == 1
    assert collector.jobs_failed == 1
    analytics = collector.source_analytics(
        "ati", SourceHealth(status=SourceStatus.ONLINE, average_duration_ms=5.0)
    )
    assert analytics.total_received == 2 and analytics.average_response_time_ms == 5.0


async def test_persister_saves_decisions_from_events(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bus = EventBus()
    DecisionPersister(repo).attach(bus)

    bus.publish(MatchingDecisionCreated(decision=_decision()))
    await asyncio.sleep(0.05)  # fire-and-forget task успевает

    assert len(await repo.get_history()) == 1


# ── Health Monitor ───────────────────────────────────────────────────────────


async def test_health_monitor_alerts_once_and_resets() -> None:
    sender = _Sender()
    state = {
        "ati": SourceHealth(
            status=SourceStatus.FAILED,
            last_success=utc_now() - timedelta(minutes=30),
            last_error="сеть",
        )
    }
    monitor = SourceHealthMonitor(
        health_provider=lambda: state, notifications=sender, unavailable_after_minutes=15
    )

    assert await monitor.check_all() == ("ati",)
    assert "недоступен" in sender.sent[0].title and "ati" in sender.sent[0].title
    assert await monitor.check_all() == ()  # повторно не спамим

    state["ati"] = SourceHealth(status=SourceStatus.ONLINE)
    await monitor.check_all()  # восстановление сбрасывает сторожок
    state["ati"] = SourceHealth(
        status=SourceStatus.FAILED, last_success=utc_now() - timedelta(minutes=30)
    )
    assert await monitor.check_all() == ("ati",)


async def test_health_monitor_ignores_fresh_failures() -> None:
    sender = _Sender()
    monitor = SourceHealthMonitor(
        health_provider=lambda: {
            "ati": SourceHealth(status=SourceStatus.FAILED, last_success=utc_now())
        },
        notifications=sender,
    )
    assert await monitor.check_all() == ()


# ── Daily Report ─────────────────────────────────────────────────────────────


async def test_daily_report_content(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await repo.save_decision(_decision(profit=Decimal(85000)))

    collector = AnalyticsCollector()
    collector.cargo_received["ati"] = 542
    collector.source_failures["ozon"] = 2

    job = DailyAnalyticsReportJob(
        matching_repository=repo,
        collector=collector,
        health_provider=lambda: {
            "ati": SourceHealth(status=SourceStatus.ONLINE),
            "ozon": SourceHealth(status=SourceStatus.FAILED),
        },
    )
    sender = _Sender()
    context = JobContext(
        logger=logging.getLogger("test"),
        notifications=sender,
        history=repo,  # HistoryRepository не используется отчётом
        settings=AppSettings,
        trace_id="t-report",
    )

    await job.run(context)

    assert len(sender.sent) == 1
    body = sender.sent[0].body
    assert "🚚 Найдено грузов: 542" in body
    assert "✅ Подходящих: 1" in body
    assert "⭐ Лучший маршрут: Москва → Санкт-Петербург" in body
    assert "💰 Средняя прибыль: 85000 ₽" in body
    assert "ozon: 2" in body
    assert sender.sent[0].trace_id == "t-report"
    assert job.spec.name == "daily_analytics_report"  # готов для Scheduler
