"""Тесты EventBus: доставка, порядок, изоляция ошибок, точный тип."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from app.buses import EventBus
from app.core.errors import BusError
from app.core.events import Event


@dataclass(frozen=True, slots=True)
class _Ping(Event):
    value: int = 0


@dataclass(frozen=True, slots=True)
class _Other(Event):
    pass


def test_publish_delivers_to_subscriber() -> None:
    bus = EventBus()
    received: list[_Ping] = []
    bus.subscribe(_Ping, received.append)

    bus.publish(_Ping(value=42))

    assert [event.value for event in received] == [42]


def test_delivery_order_is_subscription_order() -> None:
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(_Ping, lambda _: order.append("first"))
    bus.subscribe(_Ping, lambda _: order.append("second"))

    bus.publish(_Ping())

    assert order == ["first", "second"]


def test_exact_type_dispatch_only() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(_Ping, received.append)

    bus.publish(_Other())

    assert received == []


def test_failing_subscriber_does_not_break_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    received: list[_Ping] = []

    def broken(_: _Ping) -> None:
        raise RuntimeError("boom")

    bus.subscribe(_Ping, broken)
    bus.subscribe(_Ping, received.append)

    with caplog.at_level(logging.ERROR):
        bus.publish(_Ping(value=1))

    assert len(received) == 1  # второй подписчик получил событие
    assert "_Ping" in caplog.text


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[_Ping] = []
    bus.subscribe(_Ping, received.append)
    bus.unsubscribe(_Ping, received.append)

    bus.publish(_Ping())

    assert received == []


def test_duplicate_subscribe_raises() -> None:
    bus = EventBus()
    bus.subscribe(_Ping, print)
    with pytest.raises(BusError):
        bus.subscribe(_Ping, print)


def test_unsubscribe_unknown_raises() -> None:
    bus = EventBus()
    with pytest.raises(BusError):
        bus.unsubscribe(_Ping, print)
