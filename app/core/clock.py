"""Время в ядре: единая точка получения текущего момента.

Всё ядро работает в UTC; конвертация в локальное время — забота UI.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Текущее время в UTC (timezone-aware)."""
    return datetime.now(UTC)
