"""Тесты хранилищ секретов: NullSecretStore и маппинг ошибок Keyring."""

from __future__ import annotations

import keyring.errors
import pytest

from app.core.errors import SecretStoreError
from app.core.ports import SecretStore
from app.infrastructure.settings import secret_store as secret_store_module
from app.infrastructure.settings.secret_store import KeyringSecretStore, NullSecretStore


def test_null_store_roundtrip() -> None:
    store = NullSecretStore()
    assert store.get("token") is None

    store.set("token", "abc")
    assert store.get("token") == "abc"

    store.delete("token")
    assert store.get("token") is None


def test_null_store_delete_missing_is_ok() -> None:
    NullSecretStore().delete("нет такого")  # не бросает


def test_stores_satisfy_port_structurally() -> None:
    # Protocol без runtime_checkable — проверяем присвоением (mypy) и duck-тестом
    null_store: SecretStore = NullSecretStore()
    keyring_store: SecretStore = KeyringSecretStore()
    assert null_store.get("x") is None
    assert hasattr(keyring_store, "get")


def test_keyring_store_maps_backend_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> str:
        raise keyring.errors.KeyringError("backend down")

    monkeypatch.setattr(secret_store_module.keyring, "get_password", broken)
    monkeypatch.setattr(secret_store_module.keyring, "set_password", broken)

    store = KeyringSecretStore()
    with pytest.raises(SecretStoreError):
        store.get("token")
    with pytest.raises(SecretStoreError):
        store.set("token", "v")


def test_keyring_store_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[str, str] = {}

    def fake_set(service: str, name: str, value: str) -> None:
        saved[f"{service}:{name}"] = value

    def fake_get(service: str, name: str) -> str | None:
        return saved.get(f"{service}:{name}")

    monkeypatch.setattr(secret_store_module.keyring, "set_password", fake_set)
    monkeypatch.setattr(secret_store_module.keyring, "get_password", fake_get)

    store = KeyringSecretStore(service_name="TestApp")
    store.set("token", "секрет")
    assert store.get("token") == "секрет"


def test_keyring_delete_missing_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(service: str, name: str) -> None:
        raise keyring.errors.PasswordDeleteError("нет секрета")

    monkeypatch.setattr(secret_store_module.keyring, "delete_password", missing)
    KeyringSecretStore().delete("token")  # не бросает: контракт порта
