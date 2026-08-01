"""Снапшот-тесты presentation-контрактов (Stage 8.6).

Золотые файлы — ``tests/snapshots/*.json``: это ЗАФИКСИРОВАННЫЙ контракт
данных для UI-агента. Изменение формы ViewModel — осознанное решение:
перегенерируйте снапшоты командой

    LOGISTAI_UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_viewmodel_snapshots.py

и просмотрите diff в review. Детерминизм обеспечивают фиксированные
MOCK_NOW и идентификаторы мок-провайдера.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.buses import EventBus
from app.ui.viewmodels import (
    MOCK_NOW,
    MOCK_POTENTIAL_PROFIT,
    AnalyticsViewModel,
    DashboardViewModel,
    MockDashboardDataProvider,
    SourceStatusViewModel,
    mock_best_matches,
    snapshot_dict,
)

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots"
_UPDATE_ENV = "LOGISTAI_UPDATE_SNAPSHOTS"


def _assert_matches_golden(name: str, data: Any) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    if os.environ.get(_UPDATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    assert path.exists(), f"нет золотого снапшота {path.name} — {_UPDATE_ENV}=1 для генерации"
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert data == golden, f"контракт {name} изменился — обновите снапшот осознанно"


async def _dashboard() -> DashboardViewModel:
    vm = DashboardViewModel(
        provider=MockDashboardDataProvider(),
        events=EventBus(),
        clock=lambda: MOCK_NOW,
    )
    await vm.refresh()
    vm.set_recommendation_cards(mock_best_matches(), potential_profit=MOCK_POTENTIAL_PROFIT)
    return vm


async def test_dashboard_snapshot_golden() -> None:
    """Полный дашборд: статусы, транспорт, рекомендации, аналитика, журнал."""
    vm = await _dashboard()
    _assert_matches_golden("dashboard", snapshot_dict(vm.snapshot()))


def test_cargo_cards_golden() -> None:
    """Карточки рекомендаций — главный контракт для вёрстки списка грузов."""
    _assert_matches_golden("cargo_cards", snapshot_dict(mock_best_matches()))


def test_sources_golden() -> None:
    """Карточки источников: все состояния (в сети / упал / выключен)."""
    provider = MockDashboardDataProvider()
    names = provider.source_names()
    counts = provider.cargo_counts()
    cards = tuple(
        SourceStatusViewModel.from_health(
            source_id,
            names[source_id],
            health,
            cargo_count=counts[source_id],
            now=MOCK_NOW,
        )
        for source_id, health in provider.sources_health().items()
    )
    _assert_matches_golden("sources", snapshot_dict(cards))


async def test_analytics_golden() -> None:
    """Сводка аналитики дашборда."""
    provider = MockDashboardDataProvider()
    vm = AnalyticsViewModel.build(
        found_count=sum(provider.cargo_counts().values()),
        statistics=await provider.matching_statistics(),
        potential_profit=MOCK_POTENTIAL_PROFIT,
    )
    _assert_matches_golden("analytics", snapshot_dict(vm))


async def test_snapshots_are_deterministic() -> None:
    """Два независимых прогона дают идентичную форму (байт в байт)."""
    first = snapshot_dict((await _dashboard()).snapshot())
    second = snapshot_dict((await _dashboard()).snapshot())
    assert first == second
