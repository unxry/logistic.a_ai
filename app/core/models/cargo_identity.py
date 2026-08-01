"""Стабильная идентичность предложения груза."""

from __future__ import annotations

from hashlib import sha256

from app.core.models.logistics.cargo import Cargo


def cargo_offer_fingerprint(cargo: Cargo) -> str:
    """Fingerprint предложения: изменение цены/маршрута/веса даёт новый hash."""
    basis = "|".join(
        (
            cargo.source_id,
            cargo.id,
            cargo.loading_region,
            cargo.unloading_region,
            str(cargo.weight_kg),
            str(cargo.payment_amount),
        )
    )
    return sha256(basis.encode("utf-8")).hexdigest()
