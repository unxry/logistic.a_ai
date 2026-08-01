"""Тесты иерархии ошибок."""

from __future__ import annotations

from app.core.errors import (
    CommandHandlerNotFoundError,
    LogistAIError,
    TelegramAPIError,
    TelegramAuthError,
    TelegramError,
    TelegramRateLimitError,
)


def test_hierarchy() -> None:
    assert issubclass(TelegramAuthError, TelegramError)
    assert issubclass(TelegramError, LogistAIError)
    assert issubclass(CommandHandlerNotFoundError, LogistAIError)


def test_rate_limit_keeps_retry_after() -> None:
    error = TelegramRateLimitError(retry_after=7.0)
    assert error.retry_after == 7.0
    assert "7" in str(error)


def test_api_error_keeps_code_and_description() -> None:
    error = TelegramAPIError(code=400, description="Bad Request: chat not found")
    assert error.code == 400
    assert "chat not found" in error.description
