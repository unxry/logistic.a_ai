"""Провайдер BuildInfo: читает VERSION, режим — из окружения.

Единственный источник версии приложения — файл ``VERSION`` в корне проекта
(pyproject.toml читает его же через hatchling). Никаких захардкоженных строк.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.models.build_info import BuildInfo, BuildMode

_VERSION_FALLBACK = "0.0.0-unknown"
_MODE_ENV_VAR = "LOGISTAI_MODE"


def _find_version_file() -> Path | None:
    """Найти файл VERSION.

    В dev-режиме он лежит в корне репозитория (три уровня выше этого модуля).
    На этапе упаковки (.app) файл будет включён в ресурсы бандла — тогда
    сюда добавится второй кандидат. TODO(packaging): путь внутри бандла.
    """
    repo_root_version = Path(__file__).resolve().parents[3] / "VERSION"
    if repo_root_version.is_file():
        return repo_root_version
    return None


def _read_version() -> str:
    version_file = _find_version_file()
    if version_file is None:
        return _VERSION_FALLBACK
    text = version_file.read_text(encoding="utf-8").strip()
    return text or _VERSION_FALLBACK


def _read_mode() -> BuildMode:
    raw = os.environ.get(_MODE_ENV_VAR, BuildMode.DEBUG.value).strip().lower()
    try:
        return BuildMode(raw)
    except ValueError:
        return BuildMode.DEBUG


def load_build_info() -> BuildInfo:
    """Собрать BuildInfo.

    ``build_date`` и ``git_commit`` пока заглушки (``None``) — их заполнит
    скрипт упаковки, записывающий метаданные сборки рядом с приложением.
    """
    return BuildInfo(
        version=_read_version(),
        build_date=None,
        git_commit=None,
        mode=_read_mode(),
    )
