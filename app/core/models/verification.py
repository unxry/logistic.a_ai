"""Результат проверки Telegram-настроек (кнопка «Проверить»)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Итог трёхшаговой проверки: токен → чат → тестовое сообщение.

    ``error`` — человекочитаемое объяснение первого отказа (с подсказкой,
    что делать); ``bot_username`` / ``chat_title`` заполняются по мере
    прохождения шагов — UI показывает, к какому боту и чату подключились.
    """

    token_ok: bool
    chat_ok: bool
    test_sent: bool
    error: str | None = None
    bot_username: str | None = None
    chat_title: str | None = None

    @property
    def ok(self) -> bool:
        """Полный успех всех трёх шагов."""
        return self.token_ok and self.chat_ok and self.test_sent
