"""Порт канала доставки уведомлений."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models.notification import DeliveryResult, Notification


@runtime_checkable
class NotificationChannel(Protocol):
    """Канал доставки — чистый транспорт («telegram», «macos_native», …).

    Текст готовит форматтер канала (FormatterRegistry) — канал получает его
    готовым; ``notification`` передаётся для метаданных (важность, действия).
    Новый канал = один класс + регистрация в ChannelRegistry.
    Канал не бросает исключений наружу — любая проблема доставки
    возвращается как ``DeliveryResult(ok=False, error=...)``.
    """

    @property
    def channel_id(self) -> str:
        """Уникальный строковый идентификатор канала."""
        ...

    async def send(self, notification: Notification, text: str) -> DeliveryResult:
        """Доставить готовый текст; результат — всегда DeliveryResult."""
        ...
