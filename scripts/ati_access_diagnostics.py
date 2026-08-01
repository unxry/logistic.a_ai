"""Diagnose official ATI API access without printing tokens or personal data."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.models.sources import AtiTokenState
from app.core.ports.source_credentials import CRED_ACCESS_TOKEN, CRED_BOARD_ID
from app.infrastructure.settings.secret_store import KeyringSecretStore
from app.infrastructure.sources.ati import AtiClient
from app.infrastructure.sources.ati.auth import mask_secret
from app.infrastructure.sources.ati.client import (
    BOARDS_CAN_VIEW_PATH,
    BOARDS_MY_PATH,
    BOARDS_PARTICIPATING_PATH,
    BYBOARDS_PATH,
    DEFAULT_BASE_URL,
    LOADS_PATH,
)
from app.infrastructure.sources.credentials import KeychainSourceCredentialProvider

REFERENCE = "ati_main"
GENERAL_BOARD_ID = "a0a0a0a0a0a0a0a0a0a0a0a0"


@dataclass(frozen=True, slots=True)
class EndpointProbe:
    path: str
    status: int
    shape: str
    count: int | None


def _source_key(field: str) -> str:
    return f"source:{REFERENCE}:{field}"


def _count_payload(payload: Any) -> tuple[str, int | None]:
    if isinstance(payload, list):
        return "list", len(payload)
    if isinstance(payload, Mapping):
        keys = ",".join(sorted(str(key) for key in payload)[:5])
        for key in ("loads", "boards", "items", "results", "ids"):
            value = payload.get(key)
            if isinstance(value, list):
                return f"object:{keys}", len(value)
        return f"object:{keys}", None
    return type(payload).__name__, None


async def _probe(client: httpx.AsyncClient, token: str, path: str) -> EndpointProbe:
    response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    shape = "non-json"
    count: int | None = None
    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type:
        shape, count = _count_payload(response.json())
    return EndpointProbe(path=path, status=response.status_code, shape=shape, count=count)


async def main() -> int:
    """Run read-only diagnostics and print a redacted access matrix."""
    store = KeyringSecretStore()
    token = store.get(_source_key(CRED_ACCESS_TOKEN))
    board_id = store.get(_source_key(CRED_BOARD_ID)) or ""
    credentials = KeychainSourceCredentialProvider(store)
    ati = AtiClient(credentials)
    status = ati.token_status(REFERENCE)
    if token is None or status.state is AtiTokenState.MISSING:
        print("ATI authenticated: no")
        print("Token state: MISSING")
        return 2
    if status.state is AtiTokenState.EXPIRED:
        print("ATI authenticated: no")
        print("Token state: EXPIRED")
        return 3

    async with httpx.AsyncClient(base_url=DEFAULT_BASE_URL, timeout=10.0) as http:
        probes = [
            await _probe(http, token, BOARDS_CAN_VIEW_PATH),
            await _probe(http, token, BOARDS_MY_PATH),
            await _probe(http, token, BOARDS_PARTICIPATING_PATH),
            await _probe(http, token, BYBOARDS_PATH),
            await _probe(http, token, LOADS_PATH),
        ]

    can_view = next(probe for probe in probes if probe.path == BOARDS_CAN_VIEW_PATH)
    my_boards = next(probe for probe in probes if probe.path == BOARDS_MY_PATH)
    participating = next(probe for probe in probes if probe.path == BOARDS_PARTICIPATING_PATH)
    byboards = next(probe for probe in probes if probe.path == BYBOARDS_PATH)
    own_loads = next(probe for probe in probes if probe.path == LOADS_PATH)

    print("ATI authenticated: yes")
    print(f"Token state: {status.state.value.upper()}")
    if status.expires_at is not None:
        print(f"Token valid until: {status.expires_at.date().isoformat()}")
    print(
        "Available API methods: "
        + ", ".join(
            (
                BOARDS_CAN_VIEW_PATH,
                BOARDS_MY_PATH,
                BOARDS_PARTICIPATING_PATH,
                BYBOARDS_PATH,
                LOADS_PATH,
            )
        )
    )
    print(f"Configured board ID: {mask_secret(board_id) if board_id else 'not set'}")
    print(f"Available boards: {can_view.count if can_view.count is not None else 'unknown'}")
    print(f"My board IDs: {my_boards.count if my_boards.count is not None else 'unknown'}")
    print(
        "Participating board IDs: "
        f"{participating.count if participating.count is not None else 'unknown'}"
    )
    print(f"Search permission: {'yes' if byboards.status == 200 else 'no'}")
    print(
        "Personal board access: "
        f"{'yes' if (can_view.count or 0) > 0 or (participating.count or 0) > 0 else 'no'}"
    )
    print(f"Own loads access: {'yes' if own_loads.status == 200 else 'no'}")
    print("General loads access: unsupported by official carrier loads API")
    print()
    for probe in probes:
        count = "n/a" if probe.count is None else str(probe.count)
        print(f"{probe.path}: status={probe.status}, shape={probe.shape}, count={count}")

    if byboards.status == 200 and (byboards.count or 0) == 0:
        if (can_view.count or 0) == 0:
            print()
            print("Reason: no personal board with canView access was returned by ATI API")
        else:
            print()
            print("Reason: accessible personal boards returned zero loads")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
