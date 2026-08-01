"""Сервис настроек: политика загрузки/сохранения. Хранение — за портами.

Сервис не знает ни о JSON, ни о Keychain — только порты SettingsRepository,
SecretStore и EventPublisher. Все изменения настроек инициируются командой
``SaveSettings`` через CommandBus (правило проекта, ADR-0005).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.commands import SaveSettings
from app.core.errors import SecretStoreError, SettingsCorruptedError, SettingsError
from app.core.events import ErrorOccurred, SettingsChanged
from app.core.models.settings import AppSettings
from app.core.ports import EventPublisher, SecretStore, SettingsRepository
from app.core.ports.secret_store import TELEGRAM_BOT_TOKEN_KEY, TELEGRAM_CHAT_ID_KEY

logger = logging.getLogger(__name__)


class SettingsService:
    """Управление настройками приложения."""

    def __init__(
        self,
        repository: SettingsRepository,
        secret_store: SecretStore,
        event_bus: EventPublisher,
    ) -> None:
        self._repository = repository
        self._secret_store = secret_store
        self._events = event_bus
        self._current: AppSettings | None = None

    @property
    def current(self) -> AppSettings:
        """Текущие настройки (лениво загружаются при первом обращении)."""
        if self._current is None:
            return self.load()
        return self._current

    def load(self) -> AppSettings:
        """Загрузить настройки.

        Повреждённый файл не роняет приложение: репозиторий уже отправил его
        в карантин, сервис логирует, публикует ErrorOccurred и продолжает
        со значениями по умолчанию.
        """
        try:
            self._current = self._repository.load()
        except SettingsCorruptedError as exc:
            logger.exception("Файл настроек повреждён и отправлен в карантин")
            self._events.publish(ErrorOccurred(source="settings", message=str(exc)))
            self._current = AppSettings()
        except SettingsError as exc:
            logger.exception("Не удалось загрузить настройки — используются значения по умолчанию")
            self._events.publish(ErrorOccurred(source="settings", message=str(exc)))
            self._current = AppSettings()
        return self._current

    def save(self, settings: AppSettings) -> None:
        """Сохранить настройки и опубликовать SettingsChanged.

        Ошибка записи логируется, публикуется ErrorOccurred и пробрасывается —
        вызывающий (UI) должен узнать, что сохранение не удалось.
        """
        try:
            self._repository.save(settings)
        except SettingsError as exc:
            logger.exception("Не удалось сохранить настройки")
            self._events.publish(ErrorOccurred(source="settings", message=str(exc)))
            raise
        self._current = settings
        self._events.publish(SettingsChanged(settings=settings))

    def update(self, mutate: Callable[[AppSettings], AppSettings]) -> AppSettings:
        """Функциональное обновление: ``update(lambda s: replace(s, ...))``."""
        new_settings = mutate(self.current)
        self.save(new_settings)
        return new_settings

    def get_bot_token(self) -> str | None:
        """Прочитать Bot Token из системного хранилища секретов."""
        try:
            return self._secret_store.get(TELEGRAM_BOT_TOKEN_KEY)
        except SecretStoreError as exc:
            logger.exception("Хранилище секретов недоступно")
            self._events.publish(ErrorOccurred(source="secrets", message=str(exc)))
            raise

    def get_chat_id(self) -> str:
        """Прочитать Telegram Chat ID из Keychain, fallback — legacy JSON."""
        try:
            value = self._secret_store.get(TELEGRAM_CHAT_ID_KEY)
        except SecretStoreError as exc:
            logger.exception("Хранилище секретов недоступно")
            self._events.publish(ErrorOccurred(source="secrets", message=str(exc)))
            raise
        return value if value else self.current.telegram.chat_id

    def apply_bot_token(self, token: str | None) -> None:
        """Применить токен из команды: None — не менять; "" — удалить; иначе записать."""
        if token is None:
            return
        try:
            if token == "":
                self._secret_store.delete(TELEGRAM_BOT_TOKEN_KEY)
            else:
                self._secret_store.set(TELEGRAM_BOT_TOKEN_KEY, token)
        except SecretStoreError as exc:
            logger.exception("Не удалось обновить Bot Token в хранилище секретов")
            self._events.publish(ErrorOccurred(source="secrets", message=str(exc)))
            raise


class SaveSettingsHandler:
    """Обработчик команды SaveSettings (регистрируется в bootstrap).

    Поток: UI → CommandBus → этот обработчик → SettingsService → порт
    хранения → EventBus (SettingsChanged). Секрет применяется первым: если
    Keychain недоступен, настройки не перезаписываются. Транзакции между
    Keychain и файлом нет — ограничение задокументировано в ADR-0010.
    """

    def __init__(self, settings_service: SettingsService) -> None:
        self._settings = settings_service

    async def __call__(self, command: SaveSettings) -> None:
        """Применить секрет, затем сохранить настройки."""
        self._settings.apply_bot_token(command.bot_token)
        self._settings.save(command.settings)
