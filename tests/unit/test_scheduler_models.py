"""Тесты моделей планировщика: расписания, ретраи, метрики."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.models.scheduler import (
    Adaptive,
    Cron,
    Interval,
    JobMetrics,
    JobRetryPolicy,
    RunOnce,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def test_interval_first_run_immediately() -> None:
    schedule = Interval(seconds=60)
    assert schedule.next_run_at(NOW, None) == NOW


def test_interval_first_run_deferred() -> None:
    schedule = Interval(seconds=60, run_immediately=False)
    assert schedule.next_run_at(NOW, None) == NOW + timedelta(seconds=60)


def test_interval_next_run_from_last() -> None:
    schedule = Interval(seconds=60)
    last = NOW - timedelta(seconds=10)
    assert schedule.next_run_at(NOW, last) == last + timedelta(seconds=60)


def test_run_once() -> None:
    schedule = RunOnce(delay_seconds=5)
    assert schedule.next_run_at(NOW, None) == NOW + timedelta(seconds=5)
    assert schedule.next_run_at(NOW, NOW) is None  # после запуска — больше никогда


def test_cron_and_adaptive_are_placeholders() -> None:
    with pytest.raises(NotImplementedError):
        Cron(expression="*/5 * * * *").next_run_at(NOW, None)
    with pytest.raises(NotImplementedError):
        Adaptive().next_run_at(NOW, None)


def test_retry_policy_backoff() -> None:
    policy = JobRetryPolicy(max_attempts=3, delay_seconds=1.0, backoff=2.0)
    assert policy.delay_for(1) == 1.0
    assert policy.delay_for(2) == 2.0
    assert policy.delay_for(3) == 4.0


def test_metrics_properties() -> None:
    empty = JobMetrics()
    assert empty.success_rate == 0.0
    assert empty.average_duration_ms == 0.0

    metrics = JobMetrics(runs=4, failures=1, total_duration_ms=400)
    assert metrics.success_rate == 0.75
    assert metrics.average_duration_ms == 100.0
