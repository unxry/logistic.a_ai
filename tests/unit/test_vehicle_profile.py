"""Тесты модели VehicleProfile."""

from __future__ import annotations

import dataclasses

import pytest

from app.core.models.logistics.vehicle_profile import (
    BodyType,
    VehicleProfile,
    VehicleType,
)


def _profile() -> VehicleProfile:
    return VehicleProfile.create(
        name="MAN TGL",
        vehicle_type=VehicleType.TRUCK,
        body_type=BodyType.TENT,
        cargo_capacity_kg=6000,
        length_cm=620,
        width_cm=245,
        height_cm=250,
        volume_m3=38.0,
        pallet_capacity=14,
    )


def test_create_fills_id_and_timestamps() -> None:
    first = _profile()
    second = _profile()
    assert first.id != second.id
    assert first.created_at.tzinfo is not None
    assert first.updated_at == first.created_at


def test_profile_is_frozen() -> None:
    profile = _profile()
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.name = "другое"  # type: ignore[misc]


def test_defaults() -> None:
    profile = _profile()
    assert profile.max_weight_kg is None  # полная масса может быть неизвестна
    assert profile.allowed_regions == ()  # пусто = без ограничений по регионам


def test_update_via_replace() -> None:
    profile = _profile()
    updated = dataclasses.replace(profile, cargo_capacity_kg=5500)
    assert updated.cargo_capacity_kg == 5500
    assert updated.id == profile.id
