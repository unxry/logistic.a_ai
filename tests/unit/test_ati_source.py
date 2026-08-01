"""Тесты скелета ATI: порт, mapper по фикстуре, дескрипторы, конфигурация."""

from __future__ import annotations

import logging

from app.core.models.settings import AppSettings
from app.core.models.sources import SourceConfiguration, SourceContext
from app.core.ports import CargoSource
from app.infrastructure.settings.secret_store import NullSecretStore
from app.infrastructure.sources.ati import AtiSource
from app.infrastructure.sources.ati.mapper import AtiCargoMapper
from app.infrastructure.sources.credentials import KeychainSourceCredentialProvider
from app.services.sources import CargoNormalizer, SourceRegistry

ATI_FIXTURE = {
    "CargoId": "ati-777",
    "CargoTypeName": "Мебель",
    "CarTypeName": "тент",
    "LoadingCityName": "Москва",
    "UnloadingCityName": "Казань",
    "Weight": 5.0,
    "Volume": 36.0,
    "Length": 6.0,
    "Width": 2.4,
    "Height": 2.5,
    "Price": 195000,
    "Distance": 720,
    "Url": "https://ati.su/cargo/777",
}


def _source() -> AtiSource:
    return AtiSource(KeychainSourceCredentialProvider(NullSecretStore()))


def test_ati_source_satisfies_port_and_is_disabled_by_default() -> None:
    source = _source()
    assert isinstance(source, CargoSource)
    assert source.spec.enabled is False  # включается только конфигурацией
    assert source.spec.requires_credentials
    assert source.spec.capabilities.supports_weight


def test_mapper_transforms_fixture_and_normalizer_completes_chain() -> None:
    raw = AtiCargoMapper().map(ATI_FIXTURE)

    assert raw.external_id == "ati-777"
    assert raw.attributes["weight"] == "5.0 т"
    assert raw.attributes["length"] == "6.0 м"
    assert raw.attributes["volume"] == "36.0 м3"

    cargo = CargoNormalizer().normalize(raw, "ati")
    assert cargo.weight_kg == 5000
    assert cargo.length_cm == 600
    assert cargo.width_cm == 240
    assert cargo.volume_m3 == 36.0
    assert cargo.loading_region == "Москва"
    assert cargo.url == "https://ati.su/cargo/777"


async def test_fetch_without_credentials_raises_auth_error() -> None:
    """Stage 9.5: включённый ATI без учёток — честная ошибка (уведомит runtime)."""
    import pytest

    from app.core.errors import SourceAuthenticationError

    source = _source()
    config = SourceConfiguration.create("ati", credentials_reference="ati_main")
    context = SourceContext(
        logger=logging.getLogger("test"),
        settings=AppSettings,
        trace_id="t-1",
        configuration=config,
    )

    with pytest.raises(SourceAuthenticationError, match="не настроены"):
        await source.fetch(context)


def test_registry_lists_available_sources() -> None:
    registry = SourceRegistry()
    registry.register(_source())

    catalog = registry.list_available_sources()

    assert len(catalog) == 1
    descriptor = catalog[0]
    assert descriptor.id == "ati" and descriptor.name == "ATI.SU"
    assert descriptor.requires_credentials
    assert "RU" in descriptor.supported_regions
