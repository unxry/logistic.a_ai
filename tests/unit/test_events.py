"""Тесты доменных событий: неизменяемость, UTC-время, наследование."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from app.core.events import AppStarted, ErrorOccurred, TelegramStatusChanged
from app.core.models.connection import ConnectionState


def test_event_is_frozen() -> None:
    event = ErrorOccurred(source="test", message="boom")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.message = "other"  # type: ignore[misc]


def test_occurred_at_is_utc_aware() -> None:
    event = AppStarted()
    assert event.occurred_at.tzinfo is not None
    assert event.occurred_at.utcoffset() == UTC.utcoffset(None)


def test_occurred_at_can_be_overridden_kw_only() -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    event = AppStarted(occurred_at=moment)
    assert event.occurred_at == moment


def test_subclass_fields_and_defaults() -> None:
    event = TelegramStatusChanged(state=ConnectionState.CONNECTED)
    assert event.state is ConnectionState.CONNECTED
    assert event.detail == ""
    assert event.occurred_at.tzinfo is not None
