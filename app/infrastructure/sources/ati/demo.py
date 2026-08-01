"""Демо-режим ATI: реальный конвейер на httpx.MockTransport (Stage 9.5).

Полный боевой путь (auth → пагинация → mapper → normalizer → поиск →
подбор → уведомление) без внешней сети: транспорт отвечает реалистичными
payload'ами ATI, среди которых есть ДУБЛИ (проверка дедупликации) и
строковые единицы («5 т», «6.2x2.45x2.5», «120 000 руб»). Секретов нет:
демо-провайдер учёток отдаёт заведомо фиктивный токен.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.models.sources import SourceConfiguration
from app.infrastructure.sources.ati.auth import TOKEN_PATH
from app.infrastructure.sources.ati.client import SEARCH_PATH, AtiClient

DEMO_CREDENTIALS_REFERENCE = "ati_demo"
_DEMO_TOKEN = "demo-token-not-a-secret"

_PAGE_1: list[dict[str, Any]] = [
    {
        "is_demo": True,
        "id": "ati-spb-120",
        "cargo": {
            "name": "Паллеты с бытовой техникой",
            "weight": "5 т",
            "sizes": "5.0x2.0x2.2",
            "pallets": 12,
        },
        "loading": {"city_name": "Москва", "date": "2026-08-01"},
        "unloading": {"city_name": "Санкт-Петербург", "date_to": "2026-08-02"},
        "payment": {"rate_text": "120 000 руб"},
        "car_type": "тент",
        "distance": 700,
        "url": "https://ati.su/cargo/demo-spb",
    },
    {
        "is_demo": True,
        "id": "ati-kazan-90",
        "cargo": {
            "name": "Мебель",
            "weight": {"quantity": 5.5, "type": "tons"},
            "volume": "36 м3",
            "sizes": "4.8x2.0x2.1",
        },
        "loading": {"city_name": "Москва"},
        "unloading": {"city_name": "Казань"},
        "payment": {"rate_sum": 90000},
        "car_type": "тент",
        "distance": 800,
        "url": "https://ati.su/cargo/demo-kazan",
    },
    {
        "is_demo": True,
        "id": "ati-tver-35",
        "cargo": {"name": "Стройматериалы", "weight": "2400 кг"},
        "loading": {"city_name": "Москва"},
        "unloading": {"city_name": "Тверь"},
        "payment": {"rate_text": "35 000 руб"},
        "car_type": "тент",
        "distance": 170,
        "url": "https://ati.su/cargo/demo-tver",
    },
    {
        "is_demo": True,
        # Перегруз для MAN TGL (6 т): движок честно отсеет по совместимости.
        "id": "ati-heavy-200",
        "cargo": {"name": "Оборудование", "weight": "20 тонн"},
        "loading": {"city_name": "Москва"},
        "unloading": {"city_name": "Воронеж"},
        "payment": {"rate_sum": 200000},
        "car_type": "тент",
        "distance": 520,
    },
]
# ATI отдаёт грузы повторно: дубликат лучшего в той же выдаче (тест дедупа).
_PAGE_1.append(dict(_PAGE_1[0]))

# Страница 2: один новый груз + ДУБЛЬ лучшего (ATI отдаёт грузы повторно).
_PAGE_2: list[dict[str, Any]] = [
    {
        "is_demo": True,
        "id": "ati-nn-60",
        "cargo": {"name": "Продукты питания", "weight": "4 т", "sizes": "4.5x2.0x2.0"},
        "loading": {"city_name": "Москва"},
        "unloading": {"city_name": "Нижний Новгород"},
        "payment": {"rate_sum": 60000},
        "car_type": "тент",
        "distance": 420,
    },
    dict(_PAGE_1[0]),  # дубликат ati-spb-120 — дедупликация обязана отсеять
]


class DemoAtiApi:
    """Обработчик httpx.MockTransport, изображающий ATI API."""

    def __init__(self) -> None:
        self.search_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Маршрутизация демо-запросов."""
        if request.url.path == TOKEN_PATH:
            return httpx.Response(200, json={"access_token": _DEMO_TOKEN, "expires_in": 3600})
        if request.url.path == SEARCH_PATH:
            if request.headers.get("Authorization") != f"Bearer {_DEMO_TOKEN}":
                return httpx.Response(401)
            self.search_calls += 1
            body = json.loads(request.content.decode("utf-8"))
            page = int(body.get("page", 1))
            loads = {1: _PAGE_1, 2: _PAGE_2}.get(page, [])
            return httpx.Response(200, json={"loads": loads})
        return httpx.Response(404)


class DemoAtiCredentialProvider:
    """Учётки демо: фиктивный статический токен (порт SourceCredentialProvider)."""

    def get(self, credentials_reference: str, field: str) -> str | None:
        """Токен только для демо-ссылки; остальное — не настроено."""
        if credentials_reference == DEMO_CREDENTIALS_REFERENCE and field in ("api_key", "token"):
            return _DEMO_TOKEN
        return None


class DemoAtiConfigurationRepository:
    """In-memory конфигурация «ATI Москва» (порт SourceConfigurationRepository).

    Пользовательский sources.json в демо-режиме не трогается.
    """

    def __init__(self) -> None:
        self._configuration = SourceConfiguration.create(
            "ati",
            name="ATI Москва",
            enabled=True,
            credentials_reference=DEMO_CREDENTIALS_REFERENCE,
            polling_interval_seconds=300,
            max_results=50,
            filters={
                "regions": "Москва, Московская область",
                "min_weight": "1000",
                "max_weight": "20000",
            },
        )

    def get_all(self) -> tuple[SourceConfiguration, ...]:
        """Единственная демо-конфигурация."""
        return (self._configuration,)

    def get(self, source_id: str) -> SourceConfiguration | None:
        """Конфигурация ATI; других источников в демо нет."""
        return self._configuration if source_id == "ati" else None

    def save(self, configuration: SourceConfiguration) -> None:
        """Демо-хранилище обновляется в памяти."""
        self._configuration = configuration

    def delete(self, source_id: str) -> None:
        """Удаление в демо не поддерживается (намеренно no-op)."""

    def enable(self, source_id: str) -> None:
        """Включить (демо и так включено)."""

    def disable(self, source_id: str) -> None:
        """Выключить в демо нельзя — no-op."""


def build_demo_ati_client() -> tuple[AtiClient, DemoAtiApi]:
    """Клиент ATI поверх мок-транспорта (для --demo-ati и тестов)."""
    api = DemoAtiApi()
    client = AtiClient(
        DemoAtiCredentialProvider(),
        transport=httpx.MockTransport(api.handler),
    )
    return client, api
