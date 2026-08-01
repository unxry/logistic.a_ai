"""События платформы источников (для Dashboard, мониторинга и Stage 6)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.core.models.logistics.cargo import Cargo
from app.core.models.sources import SourceStatus


@dataclass(frozen=True, slots=True)
class SourceRegistered(Event):
    """Источник зарегистрирован в реестре."""

    source_id: str
    name: str


@dataclass(frozen=True, slots=True)
class SourceStarted(Event):
    """Опрос источника начат."""

    source_id: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class SourceCompleted(Event):
    """Опрос завершён успешно."""

    source_id: str
    trace_id: str
    items_count: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class SourceFailed(Event):
    """Опрос завершился ошибкой (после всех попыток)."""

    source_id: str
    trace_id: str
    error: str


@dataclass(frozen=True, slots=True)
class SourceHealthChanged(Event):
    """Статус здоровья источника изменился."""

    source_id: str
    status: SourceStatus


@dataclass(frozen=True, slots=True)
class CargoReceived(Event):
    """Получены нормализованные грузы (вход для Search Engine, Stage 6)."""

    source_id: str
    trace_id: str
    items: tuple[Cargo, ...]


@dataclass(frozen=True, slots=True)
class CargoUpdated(Event):
    """Известный груз изменился у источника (цена/маршрут/вес) — Stage 9.6.

    ``changes`` — какие поля изменились («price», «route», «weight»):
    обновлённый груз снова участвует в подборе.
    """

    source_id: str
    trace_id: str
    cargo: Cargo
    changes: tuple[str, ...] = ()
