"""Порты выполнимы: минимальные фейки удовлетворяют протоколам."""

from __future__ import annotations

from app.core.clock import utc_now
from app.core.models.notification import DeliveryResult, Notification
from app.core.models.scheduler import JobContext, JobSpec, RunOnce
from app.core.models.sources import RawCargo, SourceContext, SourceResult, SourceSpec
from app.core.ports import CargoSource, Job, NotificationChannel


class _FakeChannel:
    channel_id = "fake"

    async def send(self, notification: Notification, text: str) -> DeliveryResult:
        return DeliveryResult(channel_id=self.channel_id, ok=True)


class _FakeSource:
    spec = SourceSpec(id="fake_source", name="Фейковый источник")

    async def fetch(self, context: SourceContext) -> SourceResult:
        return SourceResult(
            source_id=self.spec.id,
            received_at=utc_now(),
            raw_items=(RawCargo(external_id="1"),),
        )


class _FakeJob:
    spec = JobSpec(name="fake_job", schedule=RunOnce())

    async def run(self, context: JobContext) -> None:
        return None


def test_fake_channel_satisfies_protocol() -> None:
    assert isinstance(_FakeChannel(), NotificationChannel)


def test_fake_source_satisfies_protocol() -> None:
    assert isinstance(_FakeSource(), CargoSource)


def test_fake_job_satisfies_protocol() -> None:
    assert isinstance(_FakeJob(), Job)


async def test_fake_channel_send() -> None:
    result = await _FakeChannel().send(Notification.create("t", "b"), "текст")
    assert result.ok and result.channel_id == "fake"
