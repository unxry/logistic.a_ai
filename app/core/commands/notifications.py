"""Команды уведомлений."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.commands.base import Command
from app.core.models.notification import DeliveryReport
from app.core.models.severity import Severity


@dataclass(frozen=True, slots=True)
class SendNotification(Command[DeliveryReport]):
    """Отправить уведомление пользователю.

    ``channels``: явные id каналов; ``None`` — все включённые в настройках.
    Единая точка для всех модулей (мониторинг, аналитика, плагины).
    """

    title: str
    body: str
    severity: Severity = Severity.INFO
    channels: tuple[str, ...] | None = None
