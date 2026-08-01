"""Configure all live credentials in macOS Keychain without printing secrets."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from getpass import getpass

from app.core.models.sources import SourceConfiguration
from app.core.ports.secret_store import (
    TELEGRAM_BOT_TOKEN_KEY,
    TELEGRAM_CHAT_ID_KEY,
    YANDEX_ROUTER_API_KEY_KEY,
)
from app.core.ports.source_credentials import (
    CRED_ACCESS_TOKEN,
    CRED_API_KEY,
    CRED_BOARD_ID,
    CRED_CLIENT_ID,
    CRED_TOKEN_EXPIRES_AT,
)
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.sources.ati.auth import mask_secret
from app.infrastructure.sources.config_repository import JsonSourceConfigurationRepository
from app.infrastructure.system.paths import PlatformPaths

ATI_REFERENCE = "ati_main"
YANDEX_REFERENCE = "yandex_routes"


def _source_key(reference: str, field: str) -> str:
    return f"source:{reference}:{field}"


def _read_secret(prompt: str) -> str:
    return getpass(prompt).strip()


def _read_expiry() -> str:
    value = input("ATI_TOKEN_EXPIRES_AT (YYYY-MM-DD): ").strip()
    if not value:
        raise SystemExit("ATI expiration date is required")
    datetime.fromisoformat(value if len(value) != 10 else value + "T23:59:59+00:00")
    return value


def _configure_source(board_id: str) -> None:
    paths = PlatformPaths()
    repository = JsonSourceConfigurationRepository(paths.config_dir / "sources.json")
    current = repository.get("ati")
    filters = {
        "api_mode": "byboards",
        "max_weight": "6000",
        "cargo_types": "тент",
    }
    if current is not None:
        filters = {**dict(current.filters), **filters}
        repository.save(
            replace(
                current,
                enabled=True,
                credentials_reference=ATI_REFERENCE,
                filters=filters,
                max_results=max(current.max_results, 100),
            )
        )
        return
    repository.save(
        SourceConfiguration.create(
            "ati",
            name="ATI Live",
            enabled=True,
            credentials_reference=ATI_REFERENCE,
            polling_interval_seconds=300,
            max_results=100,
            filters=filters,
        )
    )


def main() -> int:
    """Prompt once and store credentials in Keychain."""
    ati_client_id = _read_secret("ATI_CLIENT_ID: ")
    ati_access_token = _read_secret("ATI_ACCESS_TOKEN: ")
    ati_expires_at = _read_expiry()
    ati_board_id = input("ATI_BOARD_ID (optional, Enter to skip): ").strip()
    telegram_token = _read_secret("TELEGRAM_BOT_TOKEN: ")
    telegram_chat_id = _read_secret("TELEGRAM_CHAT_ID: ")
    yandex_key = _read_secret("YANDEX_ROUTER_API_KEY: ")

    required = {
        "ATI_CLIENT_ID": ati_client_id,
        "ATI_ACCESS_TOKEN": ati_access_token,
        "TELEGRAM_BOT_TOKEN": telegram_token,
        "TELEGRAM_CHAT_ID": telegram_chat_id,
        "YANDEX_ROUTER_API_KEY": yandex_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print("Live credentials were not stored: missing " + ", ".join(missing))
        return 2

    store = KeyringSecretStore()
    store.set(_source_key(ATI_REFERENCE, CRED_CLIENT_ID), ati_client_id)
    store.set(_source_key(ATI_REFERENCE, CRED_ACCESS_TOKEN), ati_access_token)
    store.set(_source_key(ATI_REFERENCE, CRED_TOKEN_EXPIRES_AT), ati_expires_at)
    if ati_board_id:
        store.set(_source_key(ATI_REFERENCE, CRED_BOARD_ID), ati_board_id)
    store.set(TELEGRAM_BOT_TOKEN_KEY, telegram_token)
    store.set(TELEGRAM_CHAT_ID_KEY, telegram_chat_id)
    store.set(YANDEX_ROUTER_API_KEY_KEY, yandex_key)
    # Backward-compatible lookup used by older routing settings.
    store.set(_source_key(YANDEX_REFERENCE, CRED_API_KEY), yandex_key)
    _configure_source(ati_board_id)

    print("Live credentials stored in Keychain")
    print(f"ATI client_id: {mask_secret(ati_client_id)}")
    print(f"ATI access_token: {mask_secret(ati_access_token)}")
    print(f"ATI token_expires_at: {ati_expires_at}")
    print(f"ATI board_id: {mask_secret(ati_board_id) if ati_board_id else 'not set'}")
    print(f"Telegram bot_token: {mask_secret(telegram_token)}")
    print("Telegram chat: stored")
    print(f"Yandex Router key: {mask_secret(yandex_key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
