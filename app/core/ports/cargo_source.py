"""Порт источника грузов."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models.sources import SourceContext, SourceResult, SourceSpec


@runtime_checkable
class CargoSource(Protocol):
    """Источник предложений грузов (ATI API/Browser, Ozon, WB, CSV, плагины).

    Источник — данные (spec) + одна корутина. Он НЕ знает про HTTP-клиенты,
    браузеры и базу — это детали его реализации в инфраструктуре; замена
    транспорта не меняет контракт. Ошибки — только семейство ``SourceError``.
    Возвращает «сырые» грузы (RawCargo) — нормализация не его забота.
    """

    @property
    def spec(self) -> SourceSpec:
        """Описание источника (возможности, расписание, политики)."""
        ...

    async def fetch(self, context: SourceContext) -> SourceResult:
        """Получить актуальные предложения источника."""
        ...
