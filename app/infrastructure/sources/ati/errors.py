"""Маппинг ошибок ATI API в доменные SourceError."""

from __future__ import annotations

from app.core.errors import (
    SourceAuthenticationError,
    SourceError,
    SourceRateLimitError,
    SourceUnavailableError,
)


def map_ati_status(status: int, description: str = "") -> SourceError:
    """HTTP-статус ATI → доменная ошибка (используется клиентом в Stage 5.2)."""
    detail = f"ATI {status}: {description}" if description else f"ATI HTTP {status}"
    if status in (401, 403):
        return SourceAuthenticationError(detail)
    if status == 429:
        return SourceRateLimitError(detail)
    if status >= 500:
        return SourceUnavailableError(detail)
    return SourceError(detail)
