"""Тесты базовых правил совместимости «груз ↔ профиль транспорта».

Сценарии из постановки: MAN TGL (6000 кг, 38 м³, 620×245×250, 14 паллет).
"""

from __future__ import annotations

from typing import Any

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import BasicCompatibilityChecker
from app.core.models.logistics.vehicle_profile import (
    BodyType,
    VehicleProfile,
    VehicleType,
)
from app.core.ports import CargoCompatibilityChecker

CHECKER = BasicCompatibilityChecker()


def _man_tgl(**overrides: Any) -> VehicleProfile:
    params: dict[str, Any] = {
        "name": "MAN TGL",
        "vehicle_type": VehicleType.TRUCK,
        "body_type": BodyType.TENT,
        "cargo_capacity_kg": 6000,
        "length_cm": 620,
        "width_cm": 245,
        "height_cm": 250,
        "volume_m3": 38.0,
        "pallet_capacity": 14,
    }
    params.update(overrides)
    return VehicleProfile.create(**params)


def _cargo(**overrides: Any) -> Cargo:
    params: dict[str, Any] = {
        "id": "c1",
        "source_id": "test",
        "weight_kg": 5000,
        "volume_m3": 25.0,
        "length_cm": 500,
        "width_cm": 200,
        "height_cm": 220,
    }
    params.update(overrides)
    return Cargo(**params)


def test_checker_satisfies_port() -> None:
    assert isinstance(CHECKER, CargoCompatibilityChecker)


def test_fits_scenario_from_spec() -> None:
    """Авто 6000 кг / 38 м³ / 620×245×250; груз 5000 кг / 25 м³ / 500×200×220."""
    result = CHECKER.check(_cargo(), _man_tgl())

    assert result.compatible
    assert result.rejection_reasons == ()
    assert result.score == 100
    assert result.remaining_weight_kg == 1000
    assert result.remaining_volume_m3 == 13.0
    assert result.remaining_length_cm == 120


def test_rejected_by_weight() -> None:
    result = CHECKER.check(_cargo(weight_kg=7000), _man_tgl())

    assert not result.compatible
    assert result.score == 0
    assert any("Превышена грузоподъемность" in r for r in result.rejection_reasons)
    assert result.remaining_weight_kg == -1000  # перегруз виден по знаку


def test_rejected_by_volume() -> None:
    result = CHECKER.check(_cargo(volume_m3=45.0), _man_tgl())

    assert not result.compatible
    assert any("Недостаточный объем кузова" in r for r in result.rejection_reasons)


def test_weight_boundary_is_allowed() -> None:
    result = CHECKER.check(_cargo(weight_kg=6000), _man_tgl())
    assert result.compatible
    assert result.remaining_weight_kg == 0


def test_rejected_by_length() -> None:
    result = CHECKER.check(_cargo(length_cm=700), _man_tgl())
    assert not result.compatible
    assert any("по длине" in r for r in result.rejection_reasons)


def test_rejected_by_height() -> None:
    result = CHECKER.check(_cargo(height_cm=260), _man_tgl())
    assert not result.compatible
    assert any("по высоте" in r for r in result.rejection_reasons)


def test_rejected_by_pallets() -> None:
    result = CHECKER.check(_cargo(pallet_count=20), _man_tgl())
    assert not result.compatible
    assert any("паллетомест" in r for r in result.rejection_reasons)


def test_rejected_by_body_type() -> None:
    result = CHECKER.check(_cargo(required_body_type=BodyType.REFRIGERATOR), _man_tgl())
    assert not result.compatible
    assert any("кузов" in r for r in result.rejection_reasons)


def test_body_type_none_means_any() -> None:
    result = CHECKER.check(_cargo(required_body_type=None), _man_tgl())
    assert result.compatible


def test_rejected_by_region() -> None:
    vehicle = _man_tgl(allowed_regions=("Москва", "Московская область"))
    result = CHECKER.check(_cargo(loading_region="Санкт-Петербург"), vehicle)
    assert not result.compatible
    assert any("вне зоны работы" in r for r in result.rejection_reasons)


def test_empty_allowed_regions_means_no_restriction() -> None:
    result = CHECKER.check(_cargo(loading_region="Санкт-Петербург"), _man_tgl())
    assert result.compatible


def test_missing_data_warns_but_does_not_reject() -> None:
    """Неполная карточка груза — предупреждения и штраф к score, не отказ."""
    cargo = _cargo(
        weight_kg=None,
        volume_m3=None,
        length_cm=None,
        width_cm=None,
        height_cm=None,
    )
    result = CHECKER.check(cargo, _man_tgl())

    assert result.compatible
    assert len(result.warnings) == 3  # вес, объём, габариты
    assert result.score == 70
    assert result.remaining_weight_kg is None
    assert result.remaining_volume_m3 is None
    assert result.remaining_length_cm is None


def test_multiple_reasons_accumulate() -> None:
    result = CHECKER.check(_cargo(weight_kg=7000, volume_m3=45.0, pallet_count=20), _man_tgl())
    assert not result.compatible
    assert len(result.rejection_reasons) == 3
