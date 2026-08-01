"""Fluent-построитель уведомлений.

Будущие модули пишут:
    NotificationBuilder().title("…").body("…").category(CARGO)
        .action("Открыть ATI", url).payload_item("cargo_id", id).build()
"""

from __future__ import annotations

from typing import Self
from uuid import uuid4

from app.core.models.notification import (
    Notification,
    NotificationAction,
    NotificationActionType,
    NotificationCategory,
    NotificationContext,
)
from app.core.models.severity import Severity


class NotificationBuilder:
    """Пошаговая сборка Notification (валидация — в build)."""

    def __init__(self) -> None:
        self._title = ""
        self._body = ""
        self._severity = Severity.INFO
        self._category = NotificationCategory.SYSTEM
        self._channels: list[str] = []
        self._actions: list[NotificationAction] = []
        self._payload: dict[str, str] = {}
        self._source = "system"
        self._module = ""
        self._user_action = False
        self._trace_id: str | None = None

    def title(self, title: str) -> Self:
        """Заголовок (обязателен)."""
        self._title = title
        return self

    def body(self, body: str) -> Self:
        """Текст уведомления."""
        self._body = body
        return self

    def severity(self, severity: Severity) -> Self:
        """Важность."""
        self._severity = severity
        return self

    def category(self, category: NotificationCategory) -> Self:
        """Категория."""
        self._category = category
        return self

    def channel(self, channel_id: str) -> Self:
        """Явно добавить канал (иначе решает Router)."""
        self._channels.append(channel_id)
        return self

    def action(
        self,
        label: str,
        url: str = "",
        action_id: str | None = None,
        action_type: NotificationActionType = NotificationActionType.CUSTOM,
    ) -> Self:
        """Добавить действие-кнопку."""
        self._actions.append(
            NotificationAction(
                id=action_id if action_id is not None else uuid4().hex,
                label=label,
                url=url,
                action_type=action_type,
            )
        )
        return self

    def open_cargo(self, url: str) -> Self:
        """Открыть конкретную карточку груза ATI (только cargo-specific URL)."""
        return self.action(
            "Открыть ATI",
            url,
            action_id=NotificationActionType.OPEN_CARGO.value,
            action_type=NotificationActionType.OPEN_CARGO,
        )

    def open_ati_search(self, url: str = "https://loads.ati.su/") -> Self:
        """Открыть общий поиск ATI; это НЕ ссылка на конкретный груз."""
        return self.action(
            "Открыть поиск ATI",
            url,
            action_id=NotificationActionType.OPEN_ATI_SEARCH.value,
            action_type=NotificationActionType.OPEN_ATI_SEARCH,
        )

    def payload_item(self, key: str, value: str) -> Self:
        """Добавить ссылку на сущность (cargo_id, company_id, …)."""
        self._payload[key] = value
        return self

    def source(self, source: str) -> Self:
        """Источник (scheduler, ati, manual, system, plugin…)."""
        self._source = source
        return self

    def module(self, module: str) -> Self:
        """Модуль-создатель (для фильтрации журнала)."""
        self._module = module
        return self

    def user_action(self, value: bool = True) -> Self:
        """Пометить как действие пользователя."""
        self._user_action = value
        return self

    def trace_id(self, trace_id: str) -> Self:
        """Задать сквозной идентификатор корреляции (иначе — новый UUID)."""
        self._trace_id = trace_id
        return self

    def build(self) -> Notification:
        """Собрать уведомление; пустой заголовок — ошибка."""
        if not self._title.strip():
            raise ValueError("У уведомления должен быть заголовок")
        context = NotificationContext(
            source=self._source,
            module=self._module,
            user_action=self._user_action,
            trace_id=self._trace_id if self._trace_id is not None else uuid4().hex,
        )
        return Notification.create(
            self._title,
            self._body,
            self._severity,
            tuple(self._channels) if self._channels else None,
            category=self._category,
            actions=tuple(self._actions),
            payload=dict(self._payload),
            context=context,
        )
