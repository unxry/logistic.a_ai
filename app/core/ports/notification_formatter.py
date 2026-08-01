"""Порт форматирования уведомлений для канала доставки.

Сервисы не собирают строки: превращение ``Notification`` в текст конкретного
канала (HTML Telegram, plain-текст macOS, будущие email/discord) — забота
реализации порта.
"""

from __future__ import annotations

from typing import Protocol

from app.core.models.notification import Notification


class NotificationFormatter(Protocol):
    """Текстовое представление уведомлений для канала."""

    def format(self, notification: Notification) -> str:
        """Преобразовать уведомление в текст канала."""
        ...

    def format_test_message(self) -> str:
        """Тестовое сообщение канала (кнопка «Отправить тест»)."""
        ...
