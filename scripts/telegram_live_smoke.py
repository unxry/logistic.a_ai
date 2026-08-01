"""Live Telegram smoke: getMe/getChat/sendMessage with inline keyboard."""

from __future__ import annotations

import asyncio

from app.core.models.telegram import TelegramButton
from app.core.ports.secret_store import TELEGRAM_BOT_TOKEN_KEY, TELEGRAM_CHAT_ID_KEY
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.telegram.client import TelegramClient


async def main() -> int:
    """Verify Telegram Bot API without printing token or chat_id."""
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
        long_tail = "\n".join(f"Проверка split #{index}" for index in range(1, 80))
        text = (
            "🚚 Проверка LogistAI\n"
            "Москва → Санкт-Петербург\n"
            "Чистая прибыль:\n"
            "85 000 ₽\n"
            "AI Score:\n"
            "96\n\n"
            f"{long_tail}"
        )
        await client.send_message(
            chat_id,
            text,
            buttons=(
                TelegramButton(text="Открыть ATI", url="https://loads.ati.su/"),
                TelegramButton(text="Подробнее", callback_data="details:smoke"),
                TelegramButton(text="Игнорировать", callback_data="ignore:smoke"),
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
