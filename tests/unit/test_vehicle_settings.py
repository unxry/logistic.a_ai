"""Тесты VehicleSettings: активный профиль."""

from __future__ import annotations

from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.settings import VehicleSettings


def _profile(name: str) -> VehicleProfile:
    return VehicleProfile.create(
        name=name,
        vehicle_type=VehicleType.TRUCK,
        body_type=BodyType.TENT,
        cargo_capacity_kg=6000,
        length_cm=620,
        width_cm=245,
        height_cm=250,
        volume_m3=38.0,
        pallet_capacity=14,
    )


def test_defaults_are_empty() -> None:
    settings = VehicleSettings()
    assert settings.profiles == ()
    assert settings.active_profile_id is None
    assert settings.active_profile() is None


def test_active_profile_found() -> None:
    first, second = _profile("Первый"), _profile("Второй")
    settings = VehicleSettings(profiles=(first, second), active_profile_id=second.id)

    active = settings.active_profile()

    assert active is second


def test_active_profile_missing_id_returns_none() -> None:
    settings = VehicleSettings(profiles=(_profile("Один"),), active_profile_id="нет такого")
    assert settings.active_profile() is None
