"""Форматирование сообщений Telegram: экранирование, Builder, Formatter.

Сервисы строки не собирают (правило этапа 3): весь внешний вид сообщений —
здесь. Будущие виды уведомлений (груз, ошибка, дневной отчёт, AI-рекомендация)
добавляются методами форматтера, не трогая сервис.
"""

from __future__ import annotations

from typing import Self

from app.core.models.notification import Notification, NotificationCategory
from app.core.models.severity import Severity

_SEVERITY_ICONS = {
    Severity.INFO: "ℹ️",
    Severity.SUCCESS: "✅",
    Severity.WARNING: "⚠️",
    Severity.CRITICAL: "🚨",
}

#: Иконки категорий (приоритетнее важности: категория точнее описывает смысл).
_CATEGORY_ICONS = {
    NotificationCategory.ROUTE: "🚚",
    NotificationCategory.CARGO: "📦",
    NotificationCategory.MONITOR: "📡",
    NotificationCategory.SYSTEM: "📊",
    NotificationCategory.ERROR: "🚨",
}

SEPARATOR = "━━━━━━━━━━━━━━"


def escape_html(text: str) -> str:
    """Экранировать текст для parse_mode=HTML.

    ``&`` заменяется первым, иначе испортит уже вставленные сущности.
    Пользовательские данные никогда не должны ломать разметку сообщения.
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


class TelegramMessageBuilder:
    """Fluent-построитель HTML-сообщений.

    Все пользовательские данные экранируются автоматически — сырые строки
    в разметку попасть не могут.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []

    def title(self, icon: str, text: str) -> Self:
        """Заголовок: «<иконка> <b>текст</b>»."""
        self._lines.append(f"{icon} <b>{escape_html(text)}</b>")
        return self

    def line(self, text: str = "") -> Self:
        """Обычная строка (пустая — разделитель абзацев)."""
        self._lines.append(escape_html(text))
        return self

    def key_value(self, key: str, value: str) -> Self:
        """Строка вида «ключ: <b>значение</b>»."""
        self._lines.append(f"{escape_html(key)}: <b>{escape_html(value)}</b>")
        return self

    def link(self, text: str, url: str) -> Self:
        """Строка-ссылка."""
        self._lines.append(f'<a href="{escape_html(url)}">{escape_html(text)}</a>')
        return self

    def separator(self) -> Self:
        """Тонкий разделитель между заголовком и телом."""
        self._lines.append(SEPARATOR)
        return self

    def raw_html(self, html: str) -> Self:
        """Готовая HTML-строка (использовать ТОЛЬКО с заранее экранированными данными)."""
        self._lines.append(html)
        return self

    def build(self) -> str:
        """Собрать сообщение."""
        return "\n".join(self._lines)


class TelegramNotificationFormatter:
    """NotificationFormatter для Telegram (HTML).

    Единственное место, где определяется внешний вид Telegram-уведомлений.
    Будущие форматы — новые методы (cargo_message, daily_report, ...),
    сервис при этом не меняется.
    """

    def format(self, notification: Notification) -> str:
        """Уведомление → HTML-сообщение.

        Шаблон по категории: заголовок с иконкой, разделитель, тело.
        Действия в текст НЕ вставляются — они уходят inline-кнопками
        (собирает TelegramService из ``notification.actions``).

        Покрытые виды: лучший груз (ROUTE), обновление цены (CARGO),
        источник offline/restored (MONITOR ⚠️/🟢), дневной отчёт (SYSTEM),
        ошибки Scheduler и поиска (ERROR/WARNING).
        """
        icon = self._icon(notification)
        builder = TelegramMessageBuilder().title(icon, notification.title)
        if notification.body:
            builder.separator().line(notification.body)
        return builder.build()

    @staticmethod
    def _icon(notification: Notification) -> str:
        """Иконка: восстановление — 🟢, авария монитора — ⚠️, иначе категория."""
        if notification.category is NotificationCategory.MONITOR:
            return "🟢" if notification.severity is Severity.SUCCESS else "⚠️"
        if notification.severity is Severity.CRITICAL:
            return "🚨"
        return _CATEGORY_ICONS.get(
            notification.category, _SEVERITY_ICONS.get(notification.severity, "ℹ️")
        )

    def format_test_message(self) -> str:
        """Тестовое сообщение (кнопки «Проверить» / «Отправить тест»)."""
        return (
            TelegramMessageBuilder()
            .title("✅", "LogistAI подключён")
            .line()
            .line("Тестовое сообщение доставлено — уведомления будут приходить сюда.")
            .build()
        )
