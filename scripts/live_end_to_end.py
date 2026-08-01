"""Full live commissioning: ATI → pipeline → routing → SQLite → Telegram/UI state."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from app.bootstrap import build_container
from app.container import AppContainer
from app.core.clock import utc_now
from app.core.events import (
    NotificationDelivered,
    NotificationFailed,
    RouteCacheHit,
    RouteCalculated,
    RouteFallbackUsed,
)
from app.core.models.settings import NotificationSettings
from app.core.models.sources import AtiTokenState, LivePipelineReport
from app.core.ports.source_credentials import CRED_BOARD_ID
from app.infrastructure.sources.ati.auth import mask_secret

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
)


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED>", redacted)
    return redacted


def _json_payload(report: LivePipelineReport) -> str:
    payload = asdict(report)
    payload["started_at"] = report.started_at.isoformat()
    payload["finished_at"] = report.finished_at.isoformat()
    return _redact_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _disable_telegram(container: AppContainer) -> None:
    current = container.settings_service.current
    container.settings_service._current = replace(
        current,
        notifications=NotificationSettings(enabled_channels=()),
    )


async def _save_report(container: AppContainer, report: LivePipelineReport) -> Path:
    logs_dir = container.path_provider.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"live-run-{report.started_at.strftime('%Y%m%d-%H%M%S')}.json"
    payload = _json_payload(report)
    path.write_text(payload, encoding="utf-8")
    await asyncio.to_thread(
        container.database.execute,
        "INSERT OR REPLACE INTO live_pipeline_reports "
        "(trace_id, started_at, finished_at, report_json) VALUES (?, ?, ?, ?)",
        (
            report.trace_id,
            report.started_at.isoformat(),
            report.finished_at.isoformat(),
            payload,
        ),
    )
    return path


async def _best_profit(container: AppContainer, trace_id: str) -> str:
    decisions = await container.matching_repository.get_history(limit=100)
    for decision in decisions:
        if decision.trace_id == trace_id and decision.selected and decision.profit is not None:
            return str(decision.profit)
    return ""


def _reason(raw_received: int, matched: int, route_fallbacks: int) -> str:
    if raw_received == 0:
        return (
            "No loads returned by official ATI byboards/own-loads endpoint. "
            "Official carrier API exposes personal boards, not the general ATI marketplace."
        )
    if matched == 0:
        return "Loads received, but none passed vehicle/search/matching filters."
    if route_fallbacks:
        return "Matched with route fallback; verify Yandex key/quota for exact truck routing."
    return ""


def _print_report(report: LivePipelineReport, *, path: Path, dry_run: bool) -> None:
    print("LIVE END TO END")
    print(f"Dry run: {'yes' if dry_run else 'no'}")
    print(f"ATI authentication: {'verified' if report.ati_authenticated else 'failed'}")
    print(f"ATI endpoint: {report.ati_endpoint}")
    print(f"ATI board: {report.ati_board_id_masked or 'not set'}")
    print(f"Real cargo received: {report.raw_received}")
    print(f"Normalized: {report.normalized}")
    print(f"Matched: {report.matched}")
    print(f"Routes requested: {report.routes_requested}")
    print(f"Route cache hits: {report.route_cache_hits}")
    print(f"Route fallbacks: {report.route_fallbacks}")
    print(f"Best score: {report.best_score}")
    print(f"Best net profit: {report.best_net_profit or 'n/a'}")
    print(f"Telegram sent: {report.telegram_sent}")
    print(f"Telegram failed: {report.telegram_failed}")
    print("SQLite persisted: yes")
    print(f"Report: {path}")
    if report.reason:
        print(f"Reason: {report.reason}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-cargos", type=int, default=100)
    parser.add_argument("--verbose-report", action="store_true")
    args = parser.parse_args()

    trace_id = f"live-e2e-{uuid4().hex[:12]}"
    started_at = utc_now()
    container = build_container()
    if args.dry_run or args.no_telegram:
        _disable_telegram(container)

    routes_requested = 0
    route_cache_hits = 0
    route_fallbacks = 0
    telegram_sent = 0
    telegram_failed = 0

    def on_route(_: RouteCalculated) -> None:
        nonlocal routes_requested
        routes_requested += 1

    def on_cache(_: RouteCacheHit) -> None:
        nonlocal route_cache_hits
        route_cache_hits += 1

    def on_fallback(_: RouteFallbackUsed) -> None:
        nonlocal route_fallbacks
        route_fallbacks += 1

    def on_delivered(event: NotificationDelivered) -> None:
        nonlocal telegram_sent
        if "telegram" in event.report.successful_channels:
            telegram_sent += 1

    def on_failed(event: NotificationFailed) -> None:
        nonlocal telegram_failed
        if "telegram" in event.report.failed_channels:
            telegram_failed += 1

    container.event_bus.subscribe(RouteCalculated, on_route)
    container.event_bus.subscribe(RouteCacheHit, on_cache)
    container.event_bus.subscribe(RouteFallbackUsed, on_fallback)
    container.event_bus.subscribe(NotificationDelivered, on_delivered)
    container.event_bus.subscribe(NotificationFailed, on_failed)

    try:
        token_status = container.ati_client.token_status("ati_main")
        ati_authenticated = token_status.state in (AtiTokenState.VALID, AtiTokenState.EXPIRING_SOON)
        if not ati_authenticated:
            finished_at = utc_now()
            report = LivePipelineReport(
                trace_id=trace_id,
                started_at=started_at,
                finished_at=finished_at,
                ati_authenticated=False,
                duration_ms=int((finished_at - started_at).total_seconds() * 1000),
                reason=f"ATI token state is {token_status.state.value}",
            )
            path = await _save_report(container, report)
            _print_report(report, path=path, dry_run=args.dry_run)
            return 2

        source_report = await container.source_runtime.run_source("ati", trace_id=trace_id)
        await container.recommendation_pipeline.wait_idle()
        await container.notification_service.flush()
        pipeline = container.recommendation_pipeline.last_report
        finished_at = utc_now()
        board_id = container.settings_service._secret_store.get(f"source:ati_main:{CRED_BOARD_ID}")
        matched = pipeline.compatible if pipeline is not None else 0
        route_fallback_count = route_fallbacks
        best_profit = await _best_profit(container, trace_id)
        report = LivePipelineReport(
            trace_id=trace_id,
            started_at=started_at,
            finished_at=finished_at,
            ati_authenticated=True,
            ati_endpoint="GET /v1.0/loads/search/byboards",
            ati_board_id_masked=mask_secret(board_id) if board_id else "",
            ati_pages=container.ati_client.last_pages_requested,
            raw_received=source_report.raw_count,
            mapped=source_report.raw_count,
            normalized=len(source_report.items),
            invalid=max(0, source_report.raw_count - len(source_report.items)),
            duplicates=pipeline.duplicates if pipeline is not None else 0,
            updated=pipeline.updated_count if pipeline is not None else 0,
            prefilter_rejected=pipeline.prefilter_rejected if pipeline is not None else 0,
            compatibility_rejected=pipeline.compatibility_rejected if pipeline is not None else 0,
            routes_requested=routes_requested,
            route_cache_hits=route_cache_hits,
            route_fallbacks=route_fallback_count,
            matched=matched,
            best_cargo_id=pipeline.best_cargo_id if pipeline is not None else "",
            best_score=pipeline.best_score if pipeline is not None else 0,
            best_net_profit=best_profit,
            notifications_created=pipeline.notifications_created if pipeline is not None else 0,
            telegram_sent=telegram_sent,
            telegram_failed=telegram_failed,
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
            reason=_reason(source_report.raw_count, matched, route_fallback_count),
        )
        path = await _save_report(container, report)
        _print_report(report, path=path, dry_run=args.dry_run)
        if args.verbose_report:
            print(_json_payload(report))
        return 0 if report.raw_received > 0 and (args.dry_run or report.telegram_sent > 0) else 1
    finally:
        await container.telegram_bot.stop()
        await container.ati_client.aclose()
        await container.notification_service.aclose()
        container.database.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
