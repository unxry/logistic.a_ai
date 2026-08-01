"""Тесты CargoNormalizer: единицы измерения, категории, кузов, регионы."""

from __future__ import annotations

from decimal import Decimal

from app.core.models.logistics.cargo_category import CargoCategory
from app.core.models.logistics.vehicle_profile import BodyType
from app.core.models.sources import RawCargo
from app.services.sources import CargoNormalizer

N = CargoNormalizer()


def _cargo(**attributes: str) -> RawCargo:
    return RawCargo(external_id="x1", title=" Груз ", attributes=attributes)


def test_weight_variants() -> None:
    assert N.normalize(_cargo(weight="5 тонн"), "s").weight_kg == 5000
    assert N.normalize(_cargo(weight="5 т"), "s").weight_kg == 5000
    assert N.normalize(_cargo(weight="5000 кг"), "s").weight_kg == 5000
    assert N.normalize(_cargo(weight="5"), "s").weight_kg == 5000  # без метки < 100 → тонны
    assert N.normalize(_cargo(weight="850"), "s").weight_kg == 850  # без метки ≥ 100 → кг
    assert N.normalize(_cargo(weight="2,5 т"), "s").weight_kg == 2500  # запятая
    assert N.normalize(_cargo(weight="много"), "s").weight_kg is None  # непарсибельно


def test_size_variants() -> None:
    assert N.normalize(_cargo(length="13.6"), "s").length_cm == 1360  # без метки < 20 → метры
    assert N.normalize(_cargo(length="620 см"), "s").length_cm == 620
    assert N.normalize(_cargo(width="2,45 м"), "s").width_cm == 245
    assert N.normalize(_cargo(height="250"), "s").height_cm == 250  # ≥ 20 → см


def test_volume_pallets_price_distance() -> None:
    cargo = N.normalize(
        _cargo(volume="82,5 м3", pallets="14", price="195 000 ₽", distance_km="720"), "s"
    )
    assert cargo.volume_m3 == 82.5
    assert cargo.pallet_count == 14
    assert cargo.payment_amount == Decimal("195000")
    assert cargo.distance_km == 720.0


def test_categories() -> None:
    assert N.normalize(_cargo(category="Мебель"), "s").category is CargoCategory.FURNITURE
    assert N.normalize(_cargo(category="реф. перевозка"), "s").category is (
        CargoCategory.TEMPERATURE_CONTROLLED
    )
    assert N.normalize(_cargo(), "s").category is CargoCategory.GENERAL  # нет данных
    assert N.normalize(_cargo(category="нечто"), "s").category is CargoCategory.OTHER


def test_body_type() -> None:
    assert N.normalize(_cargo(body_type="тент"), "s").required_body_type is BodyType.TENT
    assert N.normalize(_cargo(body_type="рефрижератор"), "s").required_body_type is (
        BodyType.REFRIGERATOR
    )
    assert N.normalize(_cargo(), "s").required_body_type is None


def test_regions_normalized() -> None:
    cargo = N.normalize(_cargo(loading_region="  москва ", unloading_region="Санкт-Петербург"), "s")
    assert cargo.loading_region == "Москва"
    assert cargo.unloading_region == "Санкт-Петербург"


def test_identity_preserved() -> None:
    raw = RawCargo(external_id="ati-42", title=" Стройматериалы ", url="https://x/42")
    cargo = N.normalize(raw, "ati_api")
    assert cargo.id == "ati-42"
    assert cargo.source_id == "ati_api"
    assert cargo.title == "Стройматериалы"
    assert cargo.url == "https://x/42"


def test_normalized_cargo_feeds_compatibility() -> None:
    """Сквозной смысл платформы: сырой груз → Cargo → проверка совместимости."""
    from app.core.models.logistics.compatibility import BasicCompatibilityChecker
    from app.core.models.logistics.vehicle_profile import VehicleProfile, VehicleType

    cargo = N.normalize(
        _cargo(weight="5 тонн", volume="25", length="5 м", width="2 м", height="2,2 м"),
        "s",
    )
    vehicle = VehicleProfile.create(
        name="MAN TGL",
        vehicle_type=VehicleType.TRUCK,
        body_type=BodyType.TENT,
        cargo_capacity_kg=6000,
        length_cm=620,
        width_cm=245,
        height_cm=250,
        volume_m3=38.0,
        pallet_capacity=14,
    )
    result = BasicCompatibilityChecker().check(cargo, vehicle)
    assert result.compatible and result.score == 100
