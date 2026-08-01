"""Тесты CommandBus: диспетчеризация, инварианты, аудит без утечки секретов."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from app.buses import CommandBus
from app.core.commands import Command
from app.core.errors import CommandHandlerNotFoundError, DuplicateCommandHandlerError


@dataclass(frozen=True, slots=True)
class _Echo(Command[str]):
    text: str


@dataclass(frozen=True, slots=True)
class _WithSecret(Command[None]):
    token: str


async def test_dispatch_returns_handler_result() -> None:
    bus = CommandBus()

    async def handle(command: _Echo) -> str:
        return command.text.upper()

    bus.register(_Echo, handle)

    assert await bus.dispatch(_Echo(text="ping")) == "PING"


async def test_missing_handler_raises() -> None:
    bus = CommandBus()
    with pytest.raises(CommandHandlerNotFoundError):
        await bus.dispatch(_Echo(text="ping"))


def test_duplicate_register_raises() -> None:
    bus = CommandBus()

    async def handle(_: _Echo) -> str:
        return ""

    bus.register(_Echo, handle)
    with pytest.raises(DuplicateCommandHandlerError):
        bus.register(_Echo, handle)


async def test_handler_exception_propagates_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = CommandBus()

    async def broken(_: _Echo) -> str:
        raise ValueError("boom")

    bus.register(_Echo, broken)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="boom"):
        await bus.dispatch(_Echo(text="x"))

    assert "_Echo" in caplog.text


async def test_audit_log_never_contains_command_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Критично: шина логирует имя типа, но не поля (в них бывают секреты)."""
    bus = CommandBus()

    async def handle(_: _WithSecret) -> None:
        return None

    bus.register(_WithSecret, handle)

    with caplog.at_level(logging.DEBUG):
        await bus.dispatch(_WithSecret(token="SECRET-TOKEN-123"))

    assert "_WithSecret" in caplog.text
    assert "SECRET-TOKEN-123" not in caplog.text
