"""NotificationRouter — правила выбора каналов доставки.

Вся логика маршрутизации живёт здесь: NotificationService if-ов не содержит.
Текущие правила:
1. Явные ``notification.channels`` — уважаются (пересечение с включёнными).
2. WARNING / CRITICAL — все включённые каналы.
3. INFO / SUCCESS — только основной канал (первый включённый): не будим
   пользователя всеми каналами по мелочи.
Правила уточнятся с UI настроек (пер-категорийная маршрутизация — сюда же).
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.models.notification import Notification
from app.core.models.severity import Severity

_BROADCAST = frozenset({Severity.WARNING, Severity.CRITICAL})


class NotificationRouter:
    """Выбор каналов для уведомления."""

    def __init__(self, enabled_channels_provider: Callable[[], tuple[str, ...]]) -> None:
        self._enabled = enabled_channels_provider

    def route(self, notification: Notification) -> tuple[str, ...]:
        """Вернуть id каналов доставки (может быть пусто — некуда слать)."""
        enabled = self._enabled()
        if not enabled:
            return ()
        if notification.channels is not None:
            return tuple(cid for cid in notification.channels if cid in enabled)
        if notification.severity in _BROADCAST:
            return enabled
        return (enabled[0],)
