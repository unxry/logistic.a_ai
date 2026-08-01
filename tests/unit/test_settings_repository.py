"""Тесты JsonSettingsRepository: первый запуск, атомарность, карантин, миграции."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from app.core.errors import SettingsCorruptedError, SettingsError, SettingsMigrationError
from app.core.models.logistics.vehicle_profile import BodyType, VehicleProfile, VehicleType
from app.core.models.settings import AppSettings, Theme, UISettings, VehicleSettings
from app.infrastructure.settings.json_repository import JsonSettingsRepository
from app.infrastructure.settings.migrations import apply_migrations


def _repo(tmp_path: Path) -> JsonSettingsRepository:
    return JsonSettingsRepository(tmp_path / "settings.json")


def _settings_with_profile() -> AppSettings:
    profile = VehicleProfile.create(
        name="MAN TGL",
        vehicle_type=VehicleType.TRUCK,
        body_type=BodyType.TENT,
        cargo_capacity_kg=6000,
        length_cm=620,
        width_cm=245,
        height_cm=250,
        volume_m3=38.0,
        pallet_capacity=14,
        allowed_regions=("Москва",),
    )
    return dataclasses.replace(
        AppSettings(),
        ui=UISettings(theme=Theme.LIGHT, autostart=True),
        vehicle=VehicleSettings(profiles=(profile,), active_profile_id=profile.id),
    )


def test_first_run_returns_defaults(tmp_path: Path) -> None:
    assert _repo(tmp_path).load() == AppSettings()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    """Сохранение и чтение без потерь — включая профиль транспорта."""
    repo = _repo(tmp_path)
    settings = _settings_with_profile()

    repo.save(settings)
    loaded = repo.load()

    assert loaded == settings
    assert loaded.vehicle.active_profile() is not None
    assert loaded.vehicle.active_profile().name == "MAN TGL"  # type: ignore[union-attr]


def test_save_is_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.save(AppSettings())

    assert (tmp_path / "settings.json").exists()
    assert not list(tmp_path.glob("*.tmp"))
    # файл — валидный JSON с текущей схемой
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == AppSettings().schema_version


def test_corrupted_json_is_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{битый json", encoding="utf-8")
    repo = JsonSettingsRepository(path)

    with pytest.raises(SettingsCorruptedError):
        repo.load()

    assert not path.exists()  # оригинал ушёл в карантин, не потерян
    assert list(tmp_path.glob("settings.broken-*.json"))
    assert repo.load() == AppSettings()  # после карантина — дефолты


def test_newer_schema_is_rejected_and_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

    with pytest.raises(SettingsCorruptedError):
        JsonSettingsRepository(path).load()

    assert list(tmp_path.glob("settings.broken-*.json"))


def test_save_maps_os_errors_to_settings_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ошибка записи (нет прав и т.п.) переводится в доменную SettingsError.

    Отказ ОС эмулируется monkeypatch'ем, а не chmod: некоторые песочницы CI
    не применяют права доступа, а проверяем мы именно наш маппинг
    OSError → SettingsError, а не ядро операционной системы.
    """
    repo = JsonSettingsRepository(tmp_path / "settings.json")

    def denied(self: Path, *args: object, **kwargs: object) -> int:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "write_text", denied)

    with pytest.raises(SettingsError):
        repo.save(AppSettings())


def test_garbage_values_fall_back_to_defaults(tmp_path: Path) -> None:
    """Мусор в полях не роняет загрузку — берутся дефолты модели."""
    path = tmp_path / "settings.json"
    payload = {
        "schema_version": 1,
        "ui": {"theme": "неоновая", "autostart": "да"},
        "history": {"retention_days": "много"},
        "vehicle": {"profiles": [{"id": "без остальных полей"}], "active_profile_id": ""},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    loaded = JsonSettingsRepository(path).load()
    base = AppSettings()

    assert loaded.ui.theme is base.ui.theme
    assert loaded.ui.autostart is base.ui.autostart
    assert loaded.history.retention_days == base.history.retention_days
    assert loaded.vehicle.profiles == ()  # битый профиль пропущен
    assert loaded.vehicle.active_profile_id is None


# ── Движок миграций ───────────────────────────────────────────────────────────


def test_migration_chain_applies_in_order() -> None:
    calls: list[int] = []

    def step_1(data: dict[str, object]) -> dict[str, object]:
        calls.append(1)
        return {**data, "schema_version": 2, "new_field": "x"}

    def step_2(data: dict[str, object]) -> dict[str, object]:
        calls.append(2)
        return {**data, "schema_version": 3}

    result = apply_migrations({"schema_version": 1}, {1: step_1, 2: step_2}, 3)

    assert calls == [1, 2]
    assert result["schema_version"] == 3
    assert result["new_field"] == "x"


def test_missing_migration_step_raises() -> None:
    with pytest.raises(SettingsMigrationError, match="Нет миграции"):
        apply_migrations({"schema_version": 1}, {}, 2)


def test_migration_must_bump_version() -> None:
    def lazy(data: dict[str, object]) -> dict[str, object]:
        return data  # «забыла» поднять schema_version

    with pytest.raises(SettingsMigrationError, match="не подняла версию"):
        apply_migrations({"schema_version": 1}, {1: lazy}, 2)


def test_invalid_schema_version_raises() -> None:
    with pytest.raises(SettingsMigrationError, match="Некорректная версия"):
        apply_migrations({"schema_version": "один"}, {}, 1)
