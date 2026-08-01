"""Тесты TelegramClient на httpx.MockTransport: матрица статусов, ретраи, безопасность."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx
import pytest

from app.core.errors import (
    TelegramAPIError,
    TelegramAuthError,
    TelegramChatNotFoundError,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.infrastructure.telegram.client import TelegramClient
from app.infrastructure.telegram.retry import RetryPolicy

TOKEN = "TEST-TOKEN-12345"
FAST_RETRY = RetryPolicy(max_attempts=3, base_delay=0.001, max_delay=0.002, jitter=0)


def _ok(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": payload})


def _api_error(status: int, description: str, retry_after: float | None = None) -> httpx.Response:
    body: dict[str, object] = {"ok": False, "error_code": status, "description": description}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return httpx.Response(status, json=body)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> TelegramClient:
    return TelegramClient(TOKEN, transport=httpx.MockTransport(handler), retry_policy=FAST_RETRY)


async def test_get_me_success() -> None:
    client = _client(lambda _: _ok({"id": 42, "username": "logist_bot", "first_name": "LogistAI"}))
    bot = await client.get_me()
    assert bot.id == 42
    assert bot.username == "logist_bot"
    await client.aclose()


async def test_send_message_uses_html_and_returns_message_id() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _ok({"message_id": 7})

    client = _client(handler)
    message_id = await client.send_message("100", "<b>привет</b>")

    assert message_id == 7
    assert captured[0].url.path.endswith("/sendMessage")
    payload = json.loads(captured[0].read())
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True
    assert payload["text"] == "<b>привет</b>"
    await client.aclose()


async def test_400_chat_not_found() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _api_error(400, "Bad Request: chat not found")

    client = _client(handler)
    with pytest.raises(TelegramChatNotFoundError):
        await client.get_chat("1")
    assert calls == 1  # 400 не ретраится
    await client.aclose()


async def test_400_other_is_api_error_no_retry() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _api_error(400, "Bad Request: message is too long")

    client = _client(handler)
    with pytest.raises(TelegramAPIError) as excinfo:
        await client.send_message("1", "x")
    assert excinfo.value.code == 400
    assert calls == 1
    await client.aclose()


async def test_401_is_auth_error_no_retry() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _api_error(401, "Unauthorized")

    client = _client(handler)
    with pytest.raises(TelegramAuthError):
        await client.get_me()
    assert calls == 1
    await client.aclose()


async def test_403_is_api_error_no_retry() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _api_error(403, "Forbidden: bot was blocked by the user")

    client = _client(handler)
    with pytest.raises(TelegramAPIError) as excinfo:
        await client.send_message("1", "x")
    assert excinfo.value.code == 403
    assert calls == 1
    await client.aclose()


async def test_404_means_invalid_token() -> None:
    client = _client(lambda _: httpx.Response(404, json={"ok": False, "error_code": 404}))
    with pytest.raises(TelegramAuthError):
        await client.get_me()
    await client.aclose()


async def test_429_retries_with_retry_after_and_succeeds() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _api_error(429, "Too Many Requests", retry_after=0)
        return _ok({"message_id": 1})

    client = _client(handler)
    assert await client.send_message("1", "x") == 1
    assert calls == 2
    await client.aclose()


async def test_429_exhausted_raises_rate_limit_with_retry_after() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _api_error(429, "Too Many Requests", retry_after=0)

    client = _client(handler)
    with pytest.raises(TelegramRateLimitError) as excinfo:
        await client.send_message("1", "x")
    assert calls == 3  # max_attempts
    assert excinfo.value.retry_after == 0
    await client.aclose()


async def test_500_retried_up_to_three_attempts() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _api_error(500, "Internal Server Error")

    client = _client(handler)
    with pytest.raises(TelegramAPIError) as excinfo:
        await client.get_me()
    assert excinfo.value.code == 500
    assert calls == 3
    await client.aclose()


async def test_500_then_success_recovers() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return _api_error(502, "Bad Gateway")
        return _ok({"id": 1, "username": "b"})

    client = _client(handler)
    bot = await client.get_me()
    assert bot.id == 1
    assert calls == 3
    await client.aclose()


async def test_timeout_maps_to_network_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out")

    client = _client(handler)
    with pytest.raises(TelegramNetworkError):
        await client.get_me()
    await client.aclose()


async def test_dns_and_connection_errors_map_to_network_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    client = _client(handler)
    with pytest.raises(TelegramNetworkError):
        await client.get_chat("1")
    await client.aclose()


async def test_token_never_leaks_to_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    """Безопасность: токен не попадает ни в логи, ни в тексты исключений."""

    def handler(request: httpx.Request) -> httpx.Response:
        # эмулируем транспортную ошибку, в тексте которой есть URL с токеном
        raise httpx.ConnectError(f"failed to connect to {request.url}")

    client = _client(handler)
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramNetworkError) as excinfo:
        await client.get_me()

    assert TOKEN not in str(excinfo.value)
    assert "***TOKEN***" in str(excinfo.value)  # санитизация сработала
    assert TOKEN not in caplog.text
    await client.aclose()
