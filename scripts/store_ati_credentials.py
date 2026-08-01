"""Safely store ATI live credentials in macOS Keychain.

Interactive usage:
    uv run python scripts/store_ati_credentials.py

Secrets are written to:
    source:ati_main:client_id
    source:ati_main:access_token
    source:ati_main:token_expires_at
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from getpass import getpass

from app.core.models.sources import SourceConfiguration
from app.core.ports.source_credentials import (
    CRED_ACCESS_TOKEN,
    CRED_CLIENT_ID,
    CRED_TOKEN_EXPIRES_AT,
)
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.sources.ati.auth import mask_secret
from app.infrastructure.sources.config_repository import JsonSourceConfigurationRepository
from app.infrastructure.system.paths import PlatformPaths

REFERENCE = "ati_main"


def _secret_key(field: str) -> str:
    return f"source:{REFERENCE}:{field}"


def _read_date(prompt: str) -> str:
    value = input(prompt).strip()
    if value:
        datetime.fromisoformat(value if len(value) != 10 else value + "T23:59:59+00:00")
    return value


def _ensure_source_config() -> None:
    paths = PlatformPaths()
    repository = JsonSourceConfigurationRepository(paths.config_dir / "sources.json")
    current = repository.get("ati")
    if current is not None:
        repository.save(
            replace(
                current,
                enabled=True,
                credentials_reference=REFERENCE,
                filters={
                    **dict(current.filters),
                    "api_mode": "byboards",
                    "max_weight": dict(current.filters).get("max_weight", "6000"),
                    "cargo_types": dict(current.filters).get("cargo_types", "тент"),
                },
            )
        )
        return
    repository.save(
        SourceConfiguration.create(
            "ati",
            name="ATI Live",
            enabled=True,
            credentials_reference=REFERENCE,
            polling_interval_seconds=300,
            max_results=100,
            filters={
                "api_mode": "byboards",
                "max_weight": "6000",
                "cargo_types": "тент",
            },
        )
    )


def main() -> int:
    """Prompt, store and verify ATI secrets without printing them."""
    client_id = getpass("ATI_CLIENT_ID: ").strip()
    access_token = getpass("ATI_ACCESS_TOKEN: ").strip()
    expires_at = _read_date("ATI_TOKEN_EXPIRES_AT (YYYY-MM-DD): ")
    if not client_id or not access_token or not expires_at:
        print("ATI credentials were not stored: all fields are required")
        return 2

    store = KeyringSecretStore()
    store.set(_secret_key(CRED_CLIENT_ID), client_id)
    store.set(_secret_key(CRED_ACCESS_TOKEN), access_token)
    store.set(_secret_key(CRED_TOKEN_EXPIRES_AT), expires_at)
    _ensure_source_config()

    saved_token = store.get(_secret_key(CRED_ACCESS_TOKEN))
    saved_client_id = store.get(_secret_key(CRED_CLIENT_ID))
    saved_expires_at = store.get(_secret_key(CRED_TOKEN_EXPIRES_AT))
    if not saved_token or not saved_client_id or not saved_expires_at:
        print("ATI credentials verification failed")
        return 1

    print("ATI credentials stored")
    print(f"Client ID: {mask_secret(saved_client_id)}")
    print(f"Access token: {mask_secret(saved_token)}")
    print(f"Expires at: {saved_expires_at}")
    print("Source config: ati enabled with credentials_reference=ati_main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
