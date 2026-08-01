"""Модели уведомлений: уведомление, контекст, действия, отчёты о доставке.

Notification — универсальный формат для ВСЕХ будущих модулей (мониторинг,
ATI, AI, плагины): категория, каналы, действия-кнопки, payload со ссылками
на доменные сущности и сквозной trace_id (корреляция всего жизненного цикла).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.core.clock import utc_now
from app.core.models.severity import Severity


class NotificationCategory(Enum):
    """Категория уведомления (для маршрутизации и фильтрации журнала)."""

    SYSTEM = "system"
    CARGO = "cargo"
    ROUTE = "route"
    MONITOR = "monitor"
    SECURITY = "security"
    PLUGIN = "plugin"
    USER = "user"
    TEST = "test"
    ERROR = "error"
    AI = "ai"


@dataclass(frozen=True, slots=True)
class NotificationAction:
    """Действие уведомления («Открыть ATI», «Позвонить», «Скрыть»).

    Пока рендерится ссылками (Telegram HTML); inline-кнопки — без смены модели.
    """

    id: str
    label: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class NotificationContext:
    """Происхождение уведомления: кто создал и в рамках какого процесса.

    ``trace_id`` — сквозной идентификатор корреляции: Monitor → Notification →
    канал → журнал; по нему ищется весь жизненный цикл одного груза/события.
    """

    source: str = "system"
    module: str = ""
    user_action: bool = False
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Notification:
    """Уведомление пользователю.

    ``channels``: явные id каналов; ``None`` — решает NotificationRouter.
    ``payload``: ссылки на сущности (cargo_id, company_id…) для будущих модулей.
    """

    id: str
    title: str
    body: str
    severity: Severity
    created_at: datetime
    channels: tuple[str, ...] | None = None
    category: NotificationCategory = NotificationCategory.SYSTEM
    actions: tuple[NotificationAction, ...] = ()
    payload: Mapping[str, str] = field(default_factory=dict)
    context: NotificationContext = field(default_factory=NotificationContext)

    @property
    def trace_id(self) -> str:
        """Сквозной идентификатор корреляции."""
        return self.context.trace_id

    @classmethod
    def create(
        cls,
        title: str,
        body: str,
        severity: Severity = Severity.INFO,
        channels: tuple[str, ...] | None = None,
        *,
        category: NotificationCategory = NotificationCategory.SYSTEM,
        actions: tuple[NotificationAction, ...] = (),
        payload: Mapping[str, str] | None = None,
        context: NotificationContext | None = None,
    ) -> Notification:
        """Создать уведомление с новым id и текущим временем UTC."""
        return cls(
            id=uuid4().hex,
            title=title,
            body=body,
            severity=severity,
            created_at=utc_now(),
            channels=channels,
            category=category,
            actions=actions,
            payload=payload if payload is not None else {},
            context=context if context is not None else NotificationContext(),
        )


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Результат доставки по одному каналу."""

    channel_id: str
    ok: bool
    error: str | None = None
    duration_ms: int = 0
    attempts: int = 1


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """Сводка доставки уведомления по всем каналам (+ тайминги и корреляция)."""

    notification_id: str
    results: tuple[DeliveryResult, ...]
    trace_id: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0

    @property
    def all_ok(self) -> bool:
        """Доставлено во все каналы (и каналов было больше нуля)."""
        return bool(self.results) and all(result.ok for result in self.results)

    @property
    def delivered_any(self) -> bool:
        """Доставлено хотя бы в один канал."""
        return any(result.ok for result in self.results)

    @property
    def successful_channels(self) -> tuple[str, ...]:
        """Каналы с успешной доставкой."""
        return tuple(result.channel_id for result in self.results if result.ok)

    @property
    def failed_channels(self) -> tuple[str, ...]:
        """Каналы, в которые доставить не удалось."""
        return tuple(result.channel_id for result in self.results if not result.ok)

    def failed(self) -> tuple[DeliveryResult, ...]:
        """Результаты неудачных доставок."""
        return tuple(result for result in self.results if not result.ok)
