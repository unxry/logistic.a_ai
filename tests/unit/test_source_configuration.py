"""Тесты конфигураций источников: репозиторий, провайдер учёток, эффективность."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import UnknownSourceError
from app.core.models.sources import SourceConfiguration
from app.infrastructure.settings.secret_store import NullSecretStore
from app.infrastructure.sources.config_repository import JsonSourceConfigurationRepository
from app.infrastructure.sources.credentials import KeychainSourceCredentialProvider


def _repo(tmp_path: Path) -> JsonSourceConfigurationRepository:
    return JsonSourceConfigurationRepository(tmp_path / "sources.json")


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    config = SourceConfiguration.create(
        "ati",
        name="ATI основной",
        credentials_reference="ati_main",
        polling_interval_seconds=300,
        max_results=100,
        filters={"region": "Москва"},
    )
    repo.save(config)

    loaded = repo.get("ati")
    assert loaded is not None
    assert loaded.credentials_reference == "ati_main"
    assert loaded.filters["region"] == "Москва"
    assert repo.get_all() == (loaded,)
    assert repo.get("нет") is None


def test_save_overwrites_by_source_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.save(SourceConfiguration.create("ati", polling_interval_seconds=300))
    repo.save(SourceConfiguration.create("ati", polling_interval_seconds=60))

    all_configs = repo.get_all()
    assert len(all_configs) == 1
    assert all_configs[0].polling_interval_seconds == 60


def test_enable_disable_and_delete(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.save(SourceConfiguration.create("ati", enabled=True))

    repo.disable("ati")
    config = repo.get("ati")
    assert config is not None and not config.enabled

    repo.enable("ati")
    config = repo.get("ati")
    assert config is not None and config.enabled

    with pytest.raises(UnknownSourceError):
        repo.enable("призрак")

    repo.delete("ati")
    assert repo.get_all() == ()
    repo.delete("ati")  # повторное удаление — не ошибка


def test_invalid_file_and_records_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    path.write_text("{битый", encoding="utf-8")
    assert JsonSourceConfigurationRepository(path).get_all() == ()

    path.write_text('{"configurations": [{"id": "без обязательных полей"}, 42]}', encoding="utf-8")
    assert JsonSourceConfigurationRepository(path).get_all() == ()  # битые пропущены


def test_credential_provider_uses_namespaced_keys() -> None:
    secrets = NullSecretStore()
    secrets.set("source:ati_main:api_key", "KEY-123")
    provider = KeychainSourceCredentialProvider(secrets)

    assert provider.get("ati_main", "api_key") == "KEY-123"
    assert provider.get("ati_main", "login") is None
    assert provider.get("", "api_key") is None  # пустая ссылка — секретов нет
