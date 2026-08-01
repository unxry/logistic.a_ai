"""Команды настроек."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.commands.base import Command
from app.core.models.settings import AppSettings


@dataclass(frozen=True, slots=True)
class SaveSettings(Command[None]):
    """Сохранить настройки.

    ``bot_token``: ``None`` — не менять секрет; пустая строка — удалить;
    иначе — записать в SecretStore (в JSON секрет не попадает).
    """

    settings: AppSettings
    bot_token: str | None = None
