"""Реальная проверка Telegram-подсистемы (пункт 18 этапа 3).

Запуск на своей машине (секреты из Keychain или переменных окружения):

    TELEGRAM_BOT_TOKEN="123:ABC..." TELEGRAM_CHAT_ID="123456789" \\
        uv run python scripts/telegram_smoke.py

Сценарий: getMe → getChat → тестовое сообщение (через тот же
TelegramClient и форматтер, что использует приложение).
Токен, chat_id и название чата в вывод и логи не попадают.
"""

from __future__ import annotations

import asyncio
import os
import sys

from app.core.errors import TelegramError
from app.core.ports.secret_store import TELEGRAM_BOT_TOKEN_KEY, TELEGRAM_CHAT_ID_KEY
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.telegram.client import TelegramClient
from app.infrastructure.telegram.formatting import TelegramNotificationFormatter


async def main() -> int:
    store = KeyringSecretStore()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or (store.get(TELEGRAM_BOT_TOKEN_KEY) or "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "") or (store.get(TELEGRAM_CHAT_ID_KEY) or "")
    if not token or not chat_id:
        print("Сохраните Telegram credentials в Keychain или задайте env-переменные")
        return 2

    client = TelegramClient(token)
    try:
        print("1/3 getMe…", end=" ", flush=True)
        bot = await client.get_me()
        print(f"OK — бот @{bot.username}")

        print("2/3 getChat…", end=" ", flush=True)
        await client.get_chat(chat_id)
        print("OK — Chat: verified")

        print("3/3 sendMessage…", end=" ", flush=True)
        message_id = await client.send_message(
            chat_id, TelegramNotificationFormatter().format_test_message()
        )
        print(f"OK — message_id={message_id}")

        print("\n✅ Telegram-подсистема работает: проверьте сообщение на телефоне.")
        return 0
    except TelegramError as exc:
        print(f"\n❌ {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
