"""CommandBus — асинхронная шина команд: одна команда, один обработчик.

Правило проекта (ADR-0005): изменения состояния — только через команды.
Шина ведёт аудит: логирует ИМЯ типа команды и длительность выполнения,
но НИКОГДА не поля — в полях могут быть секреты (Bot Token и т.п.).
Полноценный middleware-конвейер добавим при втором сквозном сценарии
(ретраи, транзакции) — сейчас это был бы мёртвый код.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, cast

from app.core.commands import Command
from app.core.errors import CommandHandlerNotFoundError, DuplicateCommandHandlerError

logger = logging.getLogger(__name__)


class CommandBus:
    """Диспетчер команд с типизированным результатом (``Command[R] → R``)."""

    def __init__(self) -> None:
        self._handlers: dict[type[Command[Any]], Callable[[Any], Awaitable[Any]]] = {}

    def register[C: Command[Any]](
        self,
        command_type: type[C],
        handler: Callable[[C], Awaitable[Any]],
    ) -> None:
        """Зарегистрировать обработчик; на тип команды — ровно один."""
        if command_type in self._handlers:
            raise DuplicateCommandHandlerError(command_type.__name__)
        self._handlers[command_type] = handler

    async def dispatch[R](self, command: Command[R]) -> R:
        """Выполнить команду и вернуть результат её обработчика."""
        command_name = type(command).__name__
        handler = self._handlers.get(type(command))
        if handler is None:
            raise CommandHandlerNotFoundError(command_name)

        started = perf_counter()
        logger.debug("Команда %s: старт", command_name)
        try:
            result = await handler(command)
        except Exception:
            logger.exception("Команда %s: завершилась ошибкой", command_name)
            raise
        duration_ms = (perf_counter() - started) * 1000
        logger.debug("Команда %s: выполнена за %.1f мс", command_name, duration_ms)
        return cast("R", result)
