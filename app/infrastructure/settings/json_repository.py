"""JsonSettingsRepository — реализация порта SettingsRepository.

Гарантии:
- атомарная запись: tmp-файл в том же каталоге → ``os.replace``;
- повреждённый файл не теряется: карантин ``settings.broken-<время>.json``;
- миграции ``schema_version`` до текущей версии при загрузке;
- секретов в файле нет по построению (за них отвечает SecretStore).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.core.clock import utc_now
from app.core.errors import SettingsCorruptedError, SettingsError, SettingsMigrationError
from app.core.models.settings import SCHEMA_VERSION, AppSettings
from app.infrastructure.settings.migrations import MIGRATIONS, apply_migrations
from app.infrastructure.settings.serialization import settings_from_dict, settings_to_dict

logger = logging.getLogger(__name__)


class JsonSettingsRepository:
    """Хранение настроек в JSON-файле."""

    def __init__(self, file_path: Path) -> None:
        self._path = file_path

    def load(self) -> AppSettings:
        """Прочитать настройки. Первый запуск (файла нет) — дефолты.

        Повреждённый или несовместимый файл уходит в карантин, наружу летит
        ``SettingsCorruptedError`` — политику отката решает SettingsService.
        """
        if not self._path.exists():
            return AppSettings()
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SettingsError(f"Не удалось прочитать файл настроек: {exc}") from exc
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise SettingsCorruptedError("Файл настроек не является JSON-объектом")
            migrated = apply_migrations(data, MIGRATIONS, SCHEMA_VERSION)
        except (json.JSONDecodeError, SettingsCorruptedError, SettingsMigrationError) as exc:
            quarantine = self._quarantine()
            raise SettingsCorruptedError(
                f"Файл настроек повреждён или несовместим ({exc}); оригинал сохранён: {quarantine}",
                quarantine_path=quarantine,
            ) from exc
        return settings_from_dict(migrated)

    def save(self, settings: AppSettings) -> None:
        """Атомарно сохранить настройки (tmp → os.replace)."""
        payload = json.dumps(settings_to_dict(settings), ensure_ascii=False, indent=2)
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(payload + "\n", encoding="utf-8")
            os.replace(tmp_path, self._path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise SettingsError(f"Не удалось сохранить настройки: {exc}") from exc

    def _quarantine(self) -> Path | None:
        """Убрать битый файл в карантин, не удаляя данные пользователя."""
        stamp = utc_now().strftime("%Y%m%d-%H%M%S-%f")
        target = self._path.with_name(f"settings.broken-{stamp}.json")
        try:
            os.replace(self._path, target)
        except OSError:
            logger.exception("Не удалось отправить битый файл настроек в карантин")
            return None
        return target
