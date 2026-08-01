"""AtiClient — production-доступ к ATI API (Stage 9.5).

Транспорт: httpx.AsyncClient с base_url и таймаутами 5/10/10/5 (как в
Telegram-подсистеме, ADR-0012). Клиент занимается ТРАНСПОРТНЫМИ повторами
(сеть/5xx, короткий backoff) и пагинацией; политику повторов всего опроса
и rate limit источника ведёт SourceRuntime по SourceSpec — слои повторов
не дублируются, 429 и недоступность честно поднимаются доменными ошибками.

Безопасность: значения токенов не логируются и не попадают в тексты ошибок;
заголовок Authorization собирается непосредственно перед запросом.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.errors import SourceError, SourceParsingError, SourceUnavailableError
from app.core.models.sources import AtiTokenStatus
from app.core.ports import SourceCredentialProvider
from app.infrastructure.sources.ati.auth import AtiAuthProvider
from app.infrastructure.sources.ati.errors import map_ati_status

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.ati.su"
#: Эндпоинты (при изменении контракта ATI правится только этот блок).
SEARCH_PATH = "/v1.0/loads/search"
LOADS_PATH = "/v1.0/loads"
BYBOARDS_PATH = "/v1.0/loads/search/byboards"
LOAD_PATH = "/v1.0/loads/{load_id}"

_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
_PER_PAGE = 50
_MAX_PAGES = 20  # страховка от бесконечной пагинации
_TRANSPORT_ATTEMPTS = 3  # сеть/5xx: короткие повторы на уровне транспорта
_TRANSPORT_BACKOFF = 0.5


class AtiClient:
    """Низкоуровневый клиент ATI: авторизация, поиск, детали, пагинация."""

    def __init__(
        self,
        credentials: SourceCredentialProvider,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        auth: AtiAuthProvider | None = None,
    ) -> None:
        self._auth = auth if auth is not None else AtiAuthProvider(credentials)
        self._base_url = base_url
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self.last_pages_requested = 0

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    def has_credentials(self, credentials_reference: str) -> bool:
        """Настроен ли доступ (значения секретов не читаются в логи)."""
        return self._auth.has_credentials(credentials_reference)

    def token_status(self, credentials_reference: str) -> AtiTokenStatus:
        """Состояние ATI-токена без раскрытия значения."""
        return self._auth.token_status(credentials_reference)

    async def aclose(self) -> None:
        """Graceful shutdown: закрыть httpx-клиент (зовёт composition root)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Публичные операции ────────────────────────────────────────────────────

    async def search_cargo(
        self,
        *,
        credentials_reference: str,
        max_results: int,
        filters: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        """Поиск грузов с пагинацией до ``max_results`` (фильтры — README)."""
        self.last_pages_requested = 0
        if filters.get("api_mode") == "byboards":
            payload = await self._request("GET", BYBOARDS_PATH, credentials_reference)
            self.last_pages_requested = 1
            return self._extract_loads(payload)[:max_results]

        if filters.get("api_mode") == "owned_loads":
            payload = await self._request("GET", LOADS_PATH, credentials_reference)
            self.last_pages_requested = 1
            return self._extract_loads(payload)[:max_results]

        body = self._search_body(filters)
        loads: list[dict[str, Any]] = []
        page = 1
        while len(loads) < max_results and page <= _MAX_PAGES:
            payload = await self._request(
                "POST",
                SEARCH_PATH,
                credentials_reference,
                json={**body, "page": page, "per_page": _PER_PAGE},
            )
            batch = self._extract_loads(payload)
            if not batch:
                break
            loads.extend(batch)
            page += 1
            if len(batch) < _PER_PAGE:
                break
        self.last_pages_requested = page - 1
        logger.info("ATI: поиск вернул %d грузов (страниц: %d)", len(loads[:max_results]), page - 1)
        return loads[:max_results]

    async def get_load(self, load_id: str, *, credentials_reference: str) -> dict[str, Any] | None:
        """Детали одного груза; ``None`` — груз не найден (404)."""
        try:
            payload = await self._request(
                "GET", LOAD_PATH.format(load_id=load_id), credentials_reference
            )
        except SourceError as exc:
            if "404" in str(exc):
                return None
            raise
        return payload if isinstance(payload, dict) else None

    async def verify(self, *, credentials_reference: str) -> bool:
        """Проверка доступа: удаётся ли получить действующий токен."""
        try:
            await self._auth.token(self._http(), credentials_reference)
        except SourceError:
            return False
        return True

    # ── Транспорт ─────────────────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=_TIMEOUT,
                transport=self._transport,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        credentials_reference: str,
        *,
        json: Mapping[str, Any] | None = None,
        _retry_auth: bool = True,
    ) -> Any:
        client = self._http()
        token = await self._auth.token(client, credentials_reference)
        last_error: SourceError | None = None
        for attempt in range(1, _TRANSPORT_ATTEMPTS + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.TimeoutException as exc:
                last_error = SourceUnavailableError(
                    f"ATI не ответил вовремя ({type(exc).__name__})"
                )
            except httpx.HTTPError as exc:
                last_error = SourceUnavailableError(f"ATI недоступен ({type(exc).__name__})")
            else:
                if response.status_code == 401 and _retry_auth:
                    # Токен протух: инвалидировать и повторить ОДИН раз с новым.
                    self._auth.invalidate(credentials_reference)
                    return await self._request(
                        method, path, credentials_reference, json=json, _retry_auth=False
                    )
                if response.status_code >= 500:
                    last_error = SourceUnavailableError(f"ATI HTTP {response.status_code}")
                elif response.status_code != 200:
                    raise self._map_error(response)
                else:
                    return self._parse_json(response)
            if attempt < _TRANSPORT_ATTEMPTS:
                logger.warning(
                    "ATI %s %s: попытка %d/%d не удалась, повтор",
                    method,
                    path,
                    attempt,
                    _TRANSPORT_ATTEMPTS,
                )
                await asyncio.sleep(_TRANSPORT_BACKOFF * attempt)
        assert last_error is not None  # цикл гарантирует заполнение
        raise last_error

    @staticmethod
    def _map_error(response: httpx.Response) -> SourceError:
        error = map_ati_status(response.status_code, response.reason_phrase or "")
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None and hasattr(error, "retry_after"):
            try:
                error.retry_after = float(retry_after)
            except ValueError:
                logger.debug("ATI: некорректный Retry-After %r", retry_after)
        return error

    @staticmethod
    def _parse_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise SourceParsingError("ATI вернул некорректный JSON") from exc

    # ── Формирование запроса ──────────────────────────────────────────────────

    @staticmethod
    def _search_body(filters: Mapping[str, str]) -> dict[str, Any]:
        """Пользовательские фильтры конфигурации → тело запроса ATI.

        Ключи filters (строки из sources.json): regions (через запятую),
        cargo_types, min_weight/max_weight (кг), min_price (₽).
        """
        body: dict[str, Any] = {}
        regions = [part.strip() for part in filters.get("regions", "").split(",") if part.strip()]
        if regions:
            body["from_cities"] = regions
        cargo_types = [
            part.strip() for part in filters.get("cargo_types", "").split(",") if part.strip()
        ]
        if cargo_types:
            body["cargo_types"] = cargo_types
        for source_key, target_key, scale in (
            ("min_weight", "weight_min_tons", 0.001),
            ("max_weight", "weight_max_tons", 0.001),
        ):
            raw = filters.get(source_key, "").strip()
            if raw:
                try:
                    body[target_key] = float(raw) * scale
                except ValueError:
                    logger.warning("ATI: фильтр %s=%r не число — пропущен", source_key, raw)
        min_price = filters.get("min_price", "").strip()
        if min_price:
            try:
                body["rate_min"] = float(min_price)
            except ValueError:
                logger.warning("ATI: фильтр min_price=%r не число — пропущен", min_price)
        return body

    @staticmethod
    def _extract_loads(payload: Any) -> list[dict[str, Any]]:
        """Достать список грузов из ответа (loads / items / голый список)."""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("loads", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []
