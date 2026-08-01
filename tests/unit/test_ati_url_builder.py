"""ATI cargo URL validation and deep-link safety."""

from __future__ import annotations

from app.infrastructure.sources.ati.url_builder import (
    AtiCargoUrlBuilder,
    is_ati_search_url,
    is_cargo_specific_ati_url,
    is_trusted_ati_url,
)


def test_builder_accepts_official_cargo_specific_url() -> None:
    url = AtiCargoUrlBuilder().build(
        external_cargo_id="12345",
        official_url="https://loads.ati.su/cargos/12345",
    )

    assert url == "https://loads.ati.su/cargos/12345"


def test_builder_rejects_general_search_url_for_cargo() -> None:
    assert (
        AtiCargoUrlBuilder().build(
            external_cargo_id="12345",
            official_url="https://loads.ati.su/",
        )
        is None
    )


def test_url_allowlist_rejects_malicious_urls() -> None:
    assert not is_trusted_ati_url("javascript:alert(1)")
    assert not is_trusted_ati_url("data:text/html,boom")
    assert not is_trusted_ati_url("https://evil.example/cargos/12345")


def test_search_url_and_cargo_url_are_different_semantics() -> None:
    assert is_ati_search_url("https://loads.ati.su/")
    assert not is_cargo_specific_ati_url("https://loads.ati.su/", identifiers=("12345",))
    assert is_cargo_specific_ati_url(
        "https://ati.su/cargo/12345",
        identifiers=("12345",),
    )
