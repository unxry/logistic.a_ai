"""Иерархия исключений LogistAI.

Все ошибки приложения наследуются от ``LogistAIError`` — код выше по стеку
может отличать «наши» ошибки от системных. Инфраструктурные адаптеры обязаны
переводить сырые исключения (httpx, sqlite3, keyring…) в доменные.
"""

from __future__ import annotations

from pathlib import Path


class LogistAIError(Exception):
    """Базовая ошибка приложения."""


class SettingsError(LogistAIError):
    """Ошибка загрузки, валидации или сохранения настроек."""


class SettingsCorruptedError(SettingsError):
    """Файл настроек повреждён или несовместим; оригинал отправлен в карантин."""

    def __init__(self, message: str, quarantine_path: Path | None = None) -> None:
        super().__init__(message)
        self.quarantine_path = quarantine_path


class SettingsMigrationError(SettingsError):
    """Не удалось мигрировать настройки между версиями схемы."""


class SecretStoreError(LogistAIError):
    """Хранилище секретов (Keychain) недоступно или отказало."""


class StorageError(LogistAIError):
    """Ошибка локального хранилища (SQLite, файлы)."""


class NotificationError(LogistAIError):
    """Ошибка доставки уведомления."""


class SourceError(LogistAIError):
    """Ошибка источника грузов."""


class SourceAuthenticationError(SourceError):
    """Источник отверг учётные данные."""


class SourceNetworkError(SourceError):
    """Сетевая ошибка при обращении к источнику."""


class SourceParsingError(SourceError):
    """Не удалось разобрать ответ источника."""


class SourceRateLimitError(SourceError):
    """Источник ограничил частоту запросов (retry_after — если сообщил)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SourceUnavailableError(SourceError):
    """Источник временно недоступен."""


class DuplicateSourceError(SourceError):
    """Источник с таким id уже зарегистрирован."""

    def __init__(self, source_id: str) -> None:
        super().__init__(f"Источник «{source_id}» уже зарегистрирован")
        self.source_id = source_id


class UnknownSourceError(SourceError):
    """Источник с таким id не зарегистрирован."""

    def __init__(self, source_id: str) -> None:
        super().__init__(f"Источник «{source_id}» не зарегистрирован")
        self.source_id = source_id


class PluginError(LogistAIError):
    """Ошибка загрузки или работы плагина."""


class SchedulerError(LogistAIError):
    """Ошибка планировщика фоновых задач."""


class DuplicateJobError(SchedulerError):
    """Задача с таким именем уже зарегистрирована."""

    def __init__(self, job_name: str) -> None:
        super().__init__(f"Задача «{job_name}» уже зарегистрирована")
        self.job_name = job_name


class UnknownJobError(SchedulerError):
    """Задача с таким именем не зарегистрирована."""

    def __init__(self, job_name: str) -> None:
        super().__init__(f"Задача «{job_name}» не зарегистрирована")
        self.job_name = job_name


class BusError(LogistAIError):
    """Ошибка использования шин (EventBus / CommandBus)."""


class DuplicateCommandHandlerError(BusError):
    """На тип команды уже зарегистрирован обработчик (допустим ровно один)."""

    def __init__(self, command_name: str) -> None:
        super().__init__(f"Обработчик команды {command_name} уже зарегистрирован")
        self.command_name = command_name


class CommandHandlerNotFoundError(BusError):
    """Для команды не зарегистрирован обработчик."""

    def __init__(self, command_name: str) -> None:
        super().__init__(f"Не зарегистрирован обработчик команды {command_name}")
        self.command_name = command_name


class TelegramError(LogistAIError):
    """Базовая ошибка Telegram."""


class TelegramAuthError(TelegramError):
    """Невалидный Bot Token (401)."""


class TelegramChatNotFoundError(TelegramError):
    """Чат не найден или бот не имеет к нему доступа (400)."""


class TelegramNetworkError(TelegramError):
    """Сетевая ошибка: таймаут, обрыв соединения, DNS."""


class TelegramRateLimitError(TelegramError):
    """Превышен лимит запросов (429); Telegram сообщил паузу retry_after."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Превышен лимит Telegram, повтор через {retry_after:.0f} с")
        self.retry_after = retry_after


class TelegramAPIError(TelegramError):
    """Прочая ошибка Telegram Bot API (код + описание из ответа)."""

    def __init__(self, code: int, description: str) -> None:
        super().__init__(f"Telegram API {code}: {description}")
        self.code = code
        self.description = description
