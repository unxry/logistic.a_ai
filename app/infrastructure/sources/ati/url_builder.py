"""Validated ATI cargo deep links.

The builder is intentionally conservative: it accepts an official URL returned
by ATI only when the host is trusted and the URL contains the concrete cargo
identifier. It does not pretend that the generic ATI search page is a cargo
card.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

TRUSTED_ATI_HOSTS = frozenset({"ati.su", "loads.ati.su", "www.ati.su"})
ATI_SEARCH_URL = "https://loads.ati.su/"


class AtiCargoUrlBuilder:
    """Build or validate a cargo-specific ATI URL."""

    def build(
        self,
        *,
        external_cargo_id: str = "",
        cargo_application_id: str = "",
        source_metadata: Mapping[str, object] | None = None,
        official_url: str = "",
    ) -> str | None:
        """Return cargo-specific ATI URL or ``None`` when it cannot be proven."""
        identifiers = tuple(
            candidate
            for part in (
                external_cargo_id.strip(),
                cargo_application_id.strip(),
                _metadata_value(source_metadata or {}, "cargo_application_id"),
                _metadata_value(source_metadata or {}, "CargoApplicationId"),
                _metadata_value(source_metadata or {}, "id"),
                _metadata_value(source_metadata or {}, "CargoId"),
            )
            for candidate in _identifier_candidates(part)
        )
        if is_cargo_specific_ati_url(official_url, identifiers=identifiers):
            return official_url.strip()
        return None


def is_trusted_ati_url(url: str) -> bool:
    """Validate scheme/host for ATI URLs."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        return False
    host = parsed.netloc.lower()
    return host in TRUSTED_ATI_HOSTS


def is_ati_search_url(url: str) -> bool:
    """True for the generic ATI load search entry point."""
    parsed = urlparse(url.strip())
    return (
        is_trusted_ati_url(url)
        and parsed.netloc.lower() == "loads.ati.su"
        and parsed.path
        in (
            "",
            "/",
        )
    )


def is_cargo_specific_ati_url(url: str, *, identifiers: tuple[str, ...] = ()) -> bool:
    """A cargo button must point to a trusted URL containing a cargo identifier."""
    value = url.strip()
    if not value or not is_trusted_ati_url(value) or is_ati_search_url(value):
        return False
    parsed = urlparse(value)
    haystack = f"{parsed.path}?{parsed.query}".lower()
    explicit_ids = tuple(
        candidate.lower()
        for identifier in identifiers
        for candidate in _identifier_candidates(identifier)
    )
    if explicit_ids:
        return any(identifier in haystack for identifier in explicit_ids)
    return any(char.isdigit() for char in haystack)


def _metadata_value(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    return str(value).strip() if value not in (None, "") else ""


def _identifier_candidates(identifier: str) -> tuple[str, ...]:
    """Known ATI payloads sometimes wrap numeric ids in local prefixes."""
    value = identifier.strip()
    if not value:
        return ()
    parts = [value]
    digits = "".join(char for char in value if char.isdigit())
    if digits and digits != value:
        parts.append(digits)
    return tuple(dict.fromkeys(parts))
