"""Форматтер по умолчанию: чистый текст (macOS native, будущие каналы)."""

from __future__ import annotations

from app.core.models.notification import Notification


class PlainTextFormatter:
    """NotificationFormatter без разметки."""

    def format(self, notification: Notification) -> str:
        """Тело уведомления + ссылки действий отдельными строками."""
        lines = [notification.body or notification.title]
        lines.extend(
            f"{action.label}: {action.url}" for action in notification.actions if action.url
        )
        return "\n".join(lines)

    def format_test_message(self) -> str:
        """Тестовое сообщение канала."""
        return "LogistAI подключён — уведомления будут приходить сюда."
