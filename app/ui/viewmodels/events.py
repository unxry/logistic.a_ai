"""UI Event Stream (Stage 8.6) — события презентационного слоя.

Будущие виджеты подписываются на ЭТИ три события и не знают два десятка
доменных: DashboardViewModel переводит доменный поток в презентационный.
События несут готовые к отрисовке данные — виджету не нужно ничего
дочитывать.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.events.base import Event
from app.ui.viewmodels.cards import CargoCardViewModel, DashboardSnapshot, SourceStatusViewModel


@dataclass(frozen=True, slots=True)
class DashboardUpdated(Event):
    """Состояние дашборда изменилось (несёт полный снапшот)."""

    snapshot: DashboardSnapshot


@dataclass(frozen=True, slots=True)
class CargoRecommendationChanged(Event):
    """Список рекомендованных грузов обновился (лучший — первым)."""

    cards: tuple[CargoCardViewModel, ...]


@dataclass(frozen=True, slots=True)
class SourceStatusChanged(Event):
    """Карточка источника изменилась (статус или счётчик грузов)."""

    source: SourceStatusViewModel
