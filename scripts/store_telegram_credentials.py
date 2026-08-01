"""Safely store Telegram credentials in Keychain and verify end-to-end."""

from __future__ import annotations

import asyncio
from getpass import getpass

from app.core.ports.secret_store import TELEGRAM_BOT_TOKEN_KEY, TELEGRAM_CHAT_ID_KEY
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.telegram.client import TelegramClient
from app.infrastructure.telegram.formatting import TelegramNotificationFormatter


async def _verify(token: str, chat_id: str) -> tuple[str, int]:
    client = TelegramClient(token)
    try:
        bot = await client.get_me()
        await client.get_chat(chat_id)
        message_id = await client.send_message(
            chat_id,
            TelegramNotificationFormatter().format_test_message(),
        )
        return bot.username, message_id
    finally:
        await client.aclose()


def main() -> int:
    """Prompt, store and verify Telegram credentials without printing secrets."""
    token = getpass("TELEGRAM_BOT_TOKEN: ").strip()
    chat_id = getpass("TELEGRAM_CHAT_ID: ").strip()
    if not token or not chat_id:
        print("Telegram credentials were not stored: both fields are required")
        return 2

    store = KeyringSecretStore()
    store.set(TELEGRAM_BOT_TOKEN_KEY, token)
    store.set(TELEGRAM_CHAT_ID_KEY, chat_id)
    saved_token = store.get(TELEGRAM_BOT_TOKEN_KEY)
    saved_chat_id = store.get(TELEGRAM_CHAT_ID_KEY)
    if not saved_token or not saved_chat_id:
        print("Telegram credentials verification failed")
        return 1

    try:
        username, _message_id = asyncio.run(_verify(saved_token, saved_chat_id))
    except Exception as exc:
        print(f"Telegram verification failed: {type(exc).__name__}")
        return 1

    print("Telegram connected")
    print(f"Bot: @{username}")
    print("Chat: verified")
    print("Test message: sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
