"""Manual live ATI → Matching → Telegram smoke.

Requires credentials stored by:
    uv run python scripts/store_ati_credentials.py
    uv run python scripts/store_telegram_credentials.py

No demo fixtures are used here.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from app.bootstrap import build_container
from app.container import AppContainer
from app.core.clock import utc_now
from app.core.events import NotificationDelivered, NotificationFailed
from app.core.models.notification import NotificationCategory
from app.core.models.notification_builder import NotificationBuilder
from app.core.models.severity import Severity
from app.core.models.sources import AtiPipelineReport, AtiTokenState


async def main() -> int:
    """Run one real ATI poll and one Telegram delivery."""
    container = build_container()
    telegram_sent = 0
    telegram_failed = 0

    def on_delivered(event: NotificationDelivered) -> None:
        nonlocal telegram_sent
        if "telegram" in event.report.successful_channels:
            telegram_sent += 1

    def on_failed(event: NotificationFailed) -> None:
        nonlocal telegram_failed
        if "telegram" in event.report.failed_channels:
            telegram_failed += 1

    container.event_bus.subscribe(NotificationDelivered, on_delivered)
    container.event_bus.subscribe(NotificationFailed, on_failed)

    started_at = utc_now()
    try:
        token_status = container.ati_client.token_status("ati_main")
        if token_status.state is AtiTokenState.MISSING:
            print("ATI LIVE FAILED")
            print("Account: missing credentials")
            return 2
        if token_status.state is AtiTokenState.EXPIRED:
            print("ATI LIVE FAILED")
            print("Account: token expired")
            return 3

        report = await container.source_runtime.run_source("ati", trace_id="ati-live-smoke")
        await container.recommendation_pipeline.wait_idle()
        await _send_test_notification(container)
        await container.notification_service.flush()

        pipeline = container.recommendation_pipeline.last_report
        finished_at = utc_now()
        live_report = AtiPipelineReport(
            trace_id=report.trace_id,
            started_at=started_at,
            finished_at=finished_at,
            pages_requested=container.ati_client.last_pages_requested,
            raw_received=report.raw_count,
            mapped=report.raw_count,
            normalization_failed=max(0, report.raw_count - len(report.items)),
            duplicates=pipeline.duplicates if pipeline is not None else 0,
            updated=pipeline.updated_count if pipeline is not None else 0,
            prefilter_rejected=pipeline.prefilter_rejected if pipeline is not None else 0,
            compatibility_rejected=(pipeline.compatibility_rejected if pipeline is not None else 0),
            matched=pipeline.compatible if pipeline is not None else 0,
            ranked=pipeline.ranked_count if pipeline is not None else 0,
            notifications_created=(
                (pipeline.notifications_created if pipeline is not None else 0) + 1
            ),
            telegram_sent=telegram_sent,
            telegram_failed=telegram_failed,
            best_cargo_id=pipeline.best_cargo_id if pipeline is not None else "",
        )
        _save_report(container, live_report)
        _print_report(live_report)
        if not report.success:
            return 1
        if live_report.raw_received <= 0:
            return 1
        if live_report.telegram_sent <= 0:
            return 1
        return 0
    finally:
        await container.telegram_bot.stop()
        await container.ati_client.aclose()
        await container.notification_service.aclose()
        container.database.close()


async def _send_test_notification(container: AppContainer) -> None:
    notification_service = container.notification_service
    await notification_service.send(
        NotificationBuilder()
        .title("ATI LIVE CONNECTED")
        .body("Live ATI smoke completed. Secrets are not included.")
        .severity(Severity.SUCCESS)
        .category(NotificationCategory.TEST)
        .source("ati-live-smoke")
        .trace_id("ati-live-smoke")
        .build()
    )


def _save_report(container: AppContainer, report: AtiPipelineReport) -> None:
    path_provider = container.path_provider
    path = path_provider.data_dir / "ati_live_report.json"
    payload = asdict(report)
    payload["started_at"] = report.started_at.isoformat()
    payload["finished_at"] = report.finished_at.isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_report(report: AtiPipelineReport) -> None:
    print("ATI LIVE CONNECTED")
    print("Account: authenticated")
    print(f"Pages: {report.pages_requested}")
    print(f"Received: {report.raw_received}")
    print(f"Matched: {report.matched}")
    print(f"Telegram: {'sent' if report.telegram_sent else 'failed'}")
    print()
    print("ATI LIVE RUN")
    print(f"trace_id: {report.trace_id}")
    print(f"Получено сырых: {report.raw_received}")
    print(f"Нормализовано: {report.mapped - report.normalization_failed}")
    print(f"Ошибок нормализации: {report.normalization_failed}")
    print(f"Дубликатов: {report.duplicates}")
    print(f"Обновлено: {report.updated}")
    print(f"Отброшено prefilter: {report.prefilter_rejected}")
    print(f"Не подошло машине: {report.compatibility_rejected}")
    print(f"Прошло matching: {report.matched}")
    print(f"Лучших рекомендаций: {report.ranked}")
    print(f"Отправлено в Telegram: {report.telegram_sent}")
    print(f"Ошибок Telegram: {report.telegram_failed}")
    print(f"Время: {report.duration_seconds:.2f} сек")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
