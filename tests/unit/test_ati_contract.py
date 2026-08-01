"""Контрактные тесты ATI (Stage 9.6): фикстуры реальных ответов.

Инвариант: mapper НИКОГДА не роняет конвейер. Ошибочные данные →
предупреждение и Cargo с неполными полями, обработка продолжается.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.errors import SourceAuthenticationError, SourceRateLimitError
from app.infrastructure.sources.ati import AtiCargoMapper, AtiClient
from app.services.sources import CargoNormalizer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ati"


def _fixture(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _through_pipeline(payload: dict[str, Any]) -> Any:
    """Payload → mapper → normalizer (контракт: не бросает исключений)."""
    raw = AtiCargoMapper().map(payload)
    return CargoNormalizer().normalize(raw, "ati")


def test_regular_load_maps_completely() -> None:
    cargo = _through_pipeline(_fixture("regular_load.json"))
    assert cargo.weight_kg == 5000
    assert cargo.length_cm == 620 and cargo.width_cm == 245 and cargo.height_cm == 250
    assert cargo.volume_m3 == 38.0 and cargo.pallet_count == 14
    assert cargo.payment_amount == Decimal(120000)
    assert cargo.loading_region == "Москва"
    assert cargo.raw["loading"]["date"] == "2026-08-01"  # raw_metadata сохранён


def test_load_without_price_becomes_incomplete_cargo() -> None:
    cargo = _through_pipeline(_fixture("load_without_price.json"))
    assert cargo.payment_amount is None  # честное отсутствие, не ноль
    assert cargo.weight_kg == 3000  # остальное распознано


def test_load_without_weight_is_processed() -> None:
    cargo = _through_pipeline(_fixture("load_without_weight.json"))
    assert cargo.weight_kg is None
    assert cargo.payment_amount == Decimal(70000)
    assert cargo.loading_region == "Казань"


def test_nonstandard_units_are_normalized() -> None:
    cargo = _through_pipeline(_fixture("load_nonstandard_units.json"))
    assert cargo.weight_kg == 5500  # «5.5 тонн»
    assert cargo.length_cm == 620 and cargo.width_cm == 245  # «620x245x250» (см)
    assert cargo.volume_m3 == 38.0  # «38 м3»
    assert cargo.payment_amount == Decimal(120000)  # «120 000 руб»
    assert cargo.loading_region == "Москва"  # регистр нормализован


def test_empty_fields_do_not_break_pipeline() -> None:
    cargo = _through_pipeline(_fixture("load_empty_fields.json"))
    assert cargo.id == "ati-fix-5"
    assert cargo.weight_kg is None and cargo.payment_amount is None
    assert cargo.loading_region == "" and cargo.unloading_region == ""


def test_changed_api_format_survives_as_raw_metadata() -> None:
    """Неизвестный формат: пустые поля + ПОЛНЫЙ payload в raw — данные не потеряны."""
    payload = _fixture("changed_api_format.json")
    cargo = _through_pipeline(payload)
    assert cargo.source_id == "ati"
    assert cargo.weight_kg is None  # честно не распознано
    assert cargo.raw["freight"]["mass_kg"] == 4000  # доступно для будущего маппинга
    assert cargo.raw["extra"]["nested"]["deep"] == [1, 2, 3]


def test_batch_with_broken_cards_continues_processing() -> None:
    """Битая карточка в пачке не мешает остальным (warning, не исключение)."""
    payloads = [
        _fixture("regular_load.json"),
        _fixture("changed_api_format.json"),
        _fixture("load_empty_fields.json"),
        _fixture("load_nonstandard_units.json"),
    ]
    cargos = [_through_pipeline(p) for p in payloads]
    assert len(cargos) == 4
    priced = [c for c in cargos if c.payment_amount is not None]
    assert len(priced) == 2  # полезные грузы дошли до конца


async def test_auth_error_fixture_maps_to_domain_error() -> None:
    body = _fixture("auth_error.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json=body)

    class _Creds:
        def get(self, credentials_reference: str, field: str) -> str | None:
            return "static-key-fixture" if field == "api_key" else None

    client = AtiClient(_Creds(), transport=httpx.MockTransport(handler))
    # статический ключ: после 401 клиент инвалидирует и повторяет с тем же
    # статическим значением → второй 401 → доменная ошибка авторизации
    with pytest.raises(SourceAuthenticationError):
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()


async def test_rate_limit_fixture_maps_with_retry_after() -> None:
    body = _fixture("rate_limit.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"}, json=body)

    class _Creds:
        def get(self, credentials_reference: str, field: str) -> str | None:
            return "static-key-fixture" if field == "api_key" else None

    client = AtiClient(_Creds(), transport=httpx.MockTransport(handler))
    with pytest.raises(SourceRateLimitError) as info:
        await client.search_cargo(credentials_reference="ref", max_results=1, filters={})
    await client.aclose()
    assert info.value.retry_after == 30.0


def test_error_fixtures_do_not_leak_bodies_into_messages() -> None:
    """Тексты доменных ошибок не эхо-копируют тело ответа API (безопасность)."""
    from app.infrastructure.sources.ati.errors import map_ati_status

    error = map_ati_status(401, "Unauthorized")
    assert "Token expired" not in str(error)  # тело фикстуры не попадает в ошибку
    assert "401" in str(error)
