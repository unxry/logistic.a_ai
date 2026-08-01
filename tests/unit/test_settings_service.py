"""Тесты SettingsService и полного пути команды SaveSettings через CommandBus."""

from __future__ import annotations

import dataclasses

import pytest

from app.buses import CommandBus, EventBus
from app.core.commands import SaveSettings
from app.core.errors import SettingsCorruptedError, SettingsError
from app.core.events import ErrorOccurred, SettingsChanged
from app.core.models.settings import AppSettings, TelegramSettings
from app.core.ports.secret_store import TELEGRAM_BOT_TOKEN_KEY, TELEGRAM_CHAT_ID_KEY
from app.infrastructure.settings.secret_store import NullSecretStore
from app.services.settings_service import SaveSettingsHandler, SettingsService


class FakeSettingsRepository:
    """Фейк порта SettingsRepository: память + программируемые ошибки."""

    def __init__(self) -> None:
        self.stored = AppSettings()
        self.saved: list[AppSettings] = []
        self.load_error: Exception | None = None
        self.save_error: Exception | None = None

    def load(self) -> AppSettings:
        if self.load_error is not None:
            raise self.load_error
        return self.stored

    def save(self, settings: AppSettings) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(settings)
        self.stored = settings


def _make_service(
    repo: FakeSettingsRepository | None = None,
) -> tuple[SettingsService, FakeSettingsRepository, NullSecretStore, EventBus]:
    repository = repo if repo is not None else FakeSettingsRepository()
    secrets = NullSecretStore()
    bus = EventBus()
    service = SettingsService(repository=repository, secret_store=secrets, event_bus=bus)
    return service, repository, secrets, bus


def test_load_sets_current() -> None:
    service, repo, _, _ = _make_service()
    repo.stored = dataclasses.replace(AppSettings(), telegram=TelegramSettings(chat_id="42"))

    loaded = service.load()

    assert loaded.telegram.chat_id == "42"
    assert service.current is loaded


def test_get_chat_id_prefers_keychain_over_legacy_json() -> None:
    service, repo, secrets, _ = _make_service()
    repo.stored = dataclasses.replace(AppSettings(), telegram=TelegramSettings(chat_id="legacy"))
    secrets.set(TELEGRAM_CHAT_ID_KEY, "keychain-chat")

    assert service.get_chat_id() == "keychain-chat"


def test_get_chat_id_falls_back_to_json_when_keychain_is_empty() -> None:
    service, repo, _, _ = _make_service()
    repo.stored = dataclasses.replace(AppSettings(), telegram=TelegramSettings(chat_id="legacy"))

    assert service.get_chat_id() == "legacy"


def test_corrupted_settings_fall_back_to_defaults_and_publish_error() -> None:
    service, repo, _, bus = _make_service()
    repo.load_error = SettingsCorruptedError("файл битый")
    errors: list[ErrorOccurred] = []
    bus.subscribe(ErrorOccurred, errors.append)

    loaded = service.load()

    assert loaded == AppSettings()  # приложение живёт на дефолтах
    assert len(errors) == 1
    assert errors[0].source == "settings"


def test_save_publishes_settings_changed() -> None:
    service, repo, _, bus = _make_service()
    changed: list[SettingsChanged] = []
    bus.subscribe(SettingsChanged, changed.append)
    new_settings = dataclasses.replace(AppSettings(), telegram=TelegramSettings(chat_id="7"))

    service.save(new_settings)

    assert repo.saved == [new_settings]
    assert service.current == new_settings
    assert len(changed) == 1
    assert changed[0].settings == new_settings


def test_save_error_publishes_and_raises() -> None:
    service, repo, _, bus = _make_service()
    repo.save_error = SettingsError("нет прав записи")
    errors: list[ErrorOccurred] = []
    bus.subscribe(ErrorOccurred, errors.append)

    with pytest.raises(SettingsError):
        service.save(AppSettings())

    assert len(errors) == 1


def test_update_applies_mutation() -> None:
    service, _, _, _ = _make_service()

    updated = service.update(
        lambda s: dataclasses.replace(s, telegram=TelegramSettings(chat_id="99"))
    )

    assert updated.telegram.chat_id == "99"
    assert service.current.telegram.chat_id == "99"


# ── Полный путь SaveSettings: CommandBus → Handler → Service → Repo → EventBus ─


async def test_save_settings_command_full_path() -> None:
    service, repo, secrets, bus = _make_service()
    changed: list[SettingsChanged] = []
    bus.subscribe(SettingsChanged, changed.append)

    command_bus = CommandBus()
    command_bus.register(SaveSettings, SaveSettingsHandler(service))

    new_settings = dataclasses.replace(AppSettings(), telegram=TelegramSettings(chat_id="123"))
    await command_bus.dispatch(SaveSettings(settings=new_settings, bot_token="tok-123"))

    assert repo.saved == [new_settings]
    assert secrets.get(TELEGRAM_BOT_TOKEN_KEY) == "tok-123"
    assert len(changed) == 1
    assert service.current == new_settings


async def test_save_settings_command_token_semantics() -> None:
    service, _, secrets, _ = _make_service()
    command_bus = CommandBus()
    command_bus.register(SaveSettings, SaveSettingsHandler(service))
    secrets.set(TELEGRAM_BOT_TOKEN_KEY, "старый")

    # None — секрет не трогаем
    await command_bus.dispatch(SaveSettings(settings=AppSettings(), bot_token=None))
    assert secrets.get(TELEGRAM_BOT_TOKEN_KEY) == "старый"

    # пустая строка — секрет удаляется
    await command_bus.dispatch(SaveSettings(settings=AppSettings(), bot_token=""))
    assert secrets.get(TELEGRAM_BOT_TOKEN_KEY) is None
