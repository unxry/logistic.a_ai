"""AtiAuthProvider — токены ATI без утечек (Stage 9.5).

Два режима на одну и ту же ссылку учётных данных (Keychain через
SourceCredentialProvider, секреты в коде/JSON не живут):

1. **Статический токен** — поле ``access_token`` / ``api_key`` / ``token``:
   Bearer token из кабинета ATI, запросов авторизации не требует. Если рядом
   задан ``token_expires_at``, истёкший токен не используется.
2. **Сессия** — поля ``login`` + ``password``: POST /auth/v1.0/token →
   access_token с временем жизни; токен кешируется и обновляется заранее.

Ошибки: 401 — токен инвалидируется (клиент запросит новый и повторит);
403 — SourceAuthenticationError; 429 — SourceRateLimitError (retry_after).
Значения секретов НИКОГДА не логируются и не попадают в тексты ошибок.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.core.clock import utc_now
from app.core.errors import SourceAuthenticationError, SourceError
from app.core.models.sources import AtiTokenState, AtiTokenStatus
from app.core.ports import SourceCredentialProvider
from app.core.ports.source_credentials import (
    CRED_ACCESS_TOKEN,
    CRED_API_KEY,
    CRED_LOGIN,
    CRED_PASSWORD,
    CRED_TOKEN,
    CRED_TOKEN_EXPIRES_AT,
)
from app.infrastructure.sources.ati.errors import map_ati_status

logger = logging.getLogger(__name__)

#: Эндпоинт выдачи сессионного токена (документирован в README адаптера).
TOKEN_PATH = "/auth/v1.0/token"
#: Обновляем токен заранее, не дожидаясь истечения.
_EXPIRY_MARGIN = timedelta(seconds=60)
_DEFAULT_TTL_SECONDS = 3600.0
_EXPIRING_SOON = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class _CachedToken:
    value: str
    expires_at: datetime | None  # None — статический токен, не истекает


class AtiAuthProvider:
    """Получение, кеширование, обновление и инвалидация токена ATI."""

    def __init__(
        self,
        credentials: SourceCredentialProvider,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._credentials = credentials
        self._clock = clock
        self._cache: dict[str, _CachedToken] = {}  # по credentials_reference

    def has_credentials(self, reference: str) -> bool:
        """Настроен ли доступ (статический ключ или логин+пароль)."""
        if self.token_status(reference).can_use:
            return True
        login = self._credentials.get(reference, CRED_LOGIN)
        password = self._credentials.get(reference, CRED_PASSWORD)
        return bool(login) and bool(password)

    def token_status(self, reference: str) -> AtiTokenStatus:
        """Состояние ATI access token без раскрытия значения секрета."""
        static = self._static_token(reference)
        if static is None:
            return AtiTokenStatus(AtiTokenState.MISSING)
        expires_at = self._token_expires_at(reference)
        if expires_at is None:
            return AtiTokenStatus(AtiTokenState.VALID, masked_token=mask_secret(static))
        now = self._clock()
        if expires_at <= now:
            return AtiTokenStatus(
                AtiTokenState.EXPIRED,
                expires_at=expires_at,
                masked_token=mask_secret(static),
            )
        if expires_at - now <= _EXPIRING_SOON:
            return AtiTokenStatus(
                AtiTokenState.EXPIRING_SOON,
                expires_at=expires_at,
                masked_token=mask_secret(static),
            )
        return AtiTokenStatus(
            AtiTokenState.VALID,
            expires_at=expires_at,
            masked_token=mask_secret(static),
        )

    async def token(self, client: httpx.AsyncClient, reference: str) -> str:
        """Действующий токен (из кеша, статический или свежая сессия)."""
        cached = self._cache.get(reference)
        if cached is not None and not self._expired(cached):
            return cached.value

        static = self._static_token(reference)
        if static is not None:
            status = self.token_status(reference)
            if not status.can_use:
                raise SourceAuthenticationError(
                    "ATI access_token истёк — обновите токен в настройках"
                )
            self._cache[reference] = _CachedToken(value=static, expires_at=None)
            return static

        return await self._login(client, reference)

    def invalidate(self, reference: str) -> None:
        """Сбросить кеш (после 401 клиент запросит новый токен)."""
        self._cache.pop(reference, None)
        logger.info("ATI: токен сброшен, будет запрошен заново")

    # ── Внутреннее ────────────────────────────────────────────────────────────

    def _static_token(self, reference: str) -> str | None:
        for field in (CRED_ACCESS_TOKEN, CRED_API_KEY, CRED_TOKEN):
            value = self._credentials.get(reference, field)
            if value:
                return value
        return None

    def _token_expires_at(self, reference: str) -> datetime | None:
        raw = self._credentials.get(reference, CRED_TOKEN_EXPIRES_AT)
        if not raw:
            return None
        text = raw.strip()
        try:
            if len(text) == 10:
                return datetime.fromisoformat(text + "T23:59:59+00:00")
            value = datetime.fromisoformat(text)
        except ValueError:
            logger.warning("ATI: token_expires_at задан в некорректном формате")
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=self._clock().tzinfo)
        return value

    def _expired(self, cached: _CachedToken) -> bool:
        if cached.expires_at is None:
            return False
        return self._clock() >= cached.expires_at - _EXPIRY_MARGIN

    async def _login(self, client: httpx.AsyncClient, reference: str) -> str:
        login = self._credentials.get(reference, CRED_LOGIN)
        password = self._credentials.get(reference, CRED_PASSWORD)
        if not login or not password:
            raise SourceAuthenticationError(
                "Учётные данные ATI не настроены (нужен api_key или login+password в Keychain)"
            )
        logger.info("ATI: запрашивается сессионный токен")
        try:
            response = await client.post(TOKEN_PATH, json={"login": login, "password": password})
        except httpx.HTTPError as exc:
            raise SourceError(f"ATI: не удалось получить токен — {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise map_ati_status(response.status_code, "ошибка авторизации")

        payload: dict[str, Any] = response.json()
        token = str(payload.get("access_token", ""))
        if not token:
            raise SourceAuthenticationError("ATI: ответ авторизации без access_token")
        ttl = float(payload.get("expires_in", _DEFAULT_TTL_SECONDS))
        self._cache[reference] = _CachedToken(
            value=token, expires_at=self._clock() + timedelta(seconds=ttl)
        )
        logger.info("ATI: токен получен (ttl %.0f с)", ttl)
        return token


def mask_secret(value: str) -> str:
    """Маска секрета для CLI/log-safe вывода."""
    text = value.strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:4]}{'•' * 8}{text[-4:]}"
