"""Порт точек расширения для плагинов.

Плагин получает этот объект в ``register(extensions)`` и добавляет свои
вклады колбэками — сам он не импортирует ни реестры, ни инфраструктуру
(архитектурный контракт «plugins → только core и buses»).
"""

from __future__ import annotations

from typing import Protocol

from app.core.ports.cargo_source import CargoSource
from app.core.ports.job import Job
from app.core.ports.notification_channel import NotificationChannel


class PluginExtensions(Protocol):
    """Точки расширения, доступные плагину."""

    def add_source(self, source: CargoSource) -> None:
        """Зарегистрировать источник грузов."""
        ...

    def add_channel(self, channel: NotificationChannel) -> None:
        """Зарегистрировать канал уведомлений."""
        ...

    def add_job(self, job: Job) -> None:
        """Зарегистрировать фоновую задачу."""
        ...
