"""Тесты CargoCompatibilityService: делегирование внедрённому checker'у."""

from __future__ import annotations

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.compatibility import CompatibilityResult
from app.core.models.logistics.vehicle_profile import (
    BodyType,
    VehicleProfile,
    VehicleType,
)
from app.core.ports import CargoCompatibilityChecker
from app.services.logistics.compatibility_service import CargoCompatibilityService


class _FakeChecker:
    """Фейк порта: фиксирует вызовы, возвращает маркерный результат."""

    def __init__(self) -> None:
        self.calls: list[tuple[Cargo, VehicleProfile]] = []

    def check(self, cargo: Cargo, vehicle: VehicleProfile) -> CompatibilityResult:
        self.calls.append((cargo, vehicle))
        return CompatibilityResult(compatible=True, score=77)


def _vehicle() -> VehicleProfile:
    return VehicleProfile.create(
        name="Тест",
        vehicle_type=VehicleType.VAN,
        body_type=BodyType.BOX,
        cargo_capacity_kg=1500,
        length_cm=300,
        width_cm=180,
        height_cm=180,
        volume_m3=9.0,
        pallet_capacity=4,
    )


def test_fake_checker_satisfies_port() -> None:
    assert isinstance(_FakeChecker(), CargoCompatibilityChecker)


def test_service_delegates_to_checker() -> None:
    checker = _FakeChecker()
    service = CargoCompatibilityService(checker)
    cargo = Cargo(id="c1", source_id="test")
    vehicle = _vehicle()

    result = service.check(cargo, vehicle)

    assert result.score == 77  # вернулся результат именно checker'а
    assert checker.calls == [(cargo, vehicle)]
