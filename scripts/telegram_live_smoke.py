"""Live Telegram smoke: getMe/getChat/sendMessage with inline keyboard."""

from __future__ import annotations

import argparse
import asyncio

from app.core.models.telegram import TelegramButton
from app.core.ports.secret_store import TELEGRAM_BOT_TOKEN_KEY, TELEGRAM_CHAT_ID_KEY
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.telegram.client import TelegramClient


class TelegramLongMessageTestBuilder:
    """Script-only long split test builder; never used by production formatters."""

    def build(self) -> str:
        lines = ["🚚 Проверка LogistAI", "", "Длинный split-test включён явно.", ""]
        lines.extend(f"Проверка split #{index}" for index in range(1, 80))
        return "\n".join(lines)


async def main() -> int:
    """Verify Telegram Bot API without printing token or chat_id."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-long-message", action="store_true")
    args = parser.parse_args()
    if args.test_long_message:
        print("WARNING:")
        print("Будет отправлено длинное тестовое сообщение.")

    store = KeyringSecretStore()
    token = store.get(TELEGRAM_BOT_TOKEN_KEY)
    chat_id = store.get(TELEGRAM_CHAT_ID_KEY)
    if not token or not chat_id:
        print("Telegram credentials: missing")
        return 2

    client = TelegramClient(token)
    try:
        bot = await client.get_me()
        await client.get_chat(chat_id)
        text = (
            TelegramLongMessageTestBuilder().build()
            if args.test_long_message
            else "🚚 Проверка LogistAI\n\nTelegram подключён.\nУведомления работают."
        )
        await client.send_message(
            chat_id,
            text,
            buttons=(
                TelegramButton(text="Открыть ATI", url="https://loads.ati.su/"),
                TelegramButton(text="Проверить статус", callback_data="details:smoke"),
            ),
        )
    finally:
        await client.aclose()

    print("Bot verified")
    print(f"Bot: @{bot.username}")
    print("Chat verified")
    print("Message sent")
    print("Buttons sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
