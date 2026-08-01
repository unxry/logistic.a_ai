"""Совместимость «груз ↔ профиль транспорта»: результат и базовые правила.

Совместимость — понятие домена, отделённое от поиска грузов (ADR-0009):
поиск/мониторинг — это оркестрация источников, а «подходит ли груз моей
машине» — чистая функция от двух моделей. Здесь нет ни I/O, ни зависимостей.

Осознанные упрощения DRAFT (уточним с реальными источниками):
- габариты сравниваются по осям, без поворотов груза;
- регионы сопоставляются точным совпадением строк;
- отсутствие данных у груза — предупреждение (штраф к score), не отказ.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.models.logistics.cargo import Cargo
from app.core.models.logistics.vehicle_profile import VehicleProfile

_MAX_SCORE = 100
_WARNING_PENALTY = 10


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    """Итог проверки совместимости.

    ``score``: 0 — несовместим; 100 — полное совпадение при полных данных
    (каждое предупреждение о неполных данных снимает 10).
    ``remaining_*`` — запас после погрузки; ``None``, если данных нет
    (при отказе значение может быть отрицательным — это информативно).
    """

    compatible: bool
    score: int
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    remaining_weight_kg: int | None = None
    remaining_volume_m3: float | None = None
    remaining_length_cm: int | None = None


class BasicCompatibilityChecker:
    """Базовые правила совместимости (реализация порта CargoCompatibilityChecker).

    Правила: грузоподъёмность, объём, габариты, паллетоместа, тип кузова,
    регион загрузки. Альтернативные алгоритмы (скоринг, поворот груза)
    смогут прийти отдельными реализациями порта, в том числе из плагинов.
    """

    def check(self, cargo: Cargo, vehicle: VehicleProfile) -> CompatibilityResult:
        """Проверить груз против профиля; исключений не бросает."""
        reasons: list[str] = []
        warnings: list[str] = []

        remaining_weight = self._check_weight(cargo, vehicle, reasons, warnings)
        remaining_volume = self._check_volume(cargo, vehicle, reasons, warnings)
        remaining_length = self._check_dimensions(cargo, vehicle, reasons, warnings)
        self._check_pallets(cargo, vehicle, reasons)
        self._check_body_type(cargo, vehicle, reasons)
        self._check_region(cargo, vehicle, reasons)

        compatible = not reasons
        score = max(0, _MAX_SCORE - _WARNING_PENALTY * len(warnings)) if compatible else 0
        return CompatibilityResult(
            compatible=compatible,
            score=score,
            rejection_reasons=tuple(reasons),
            warnings=tuple(warnings),
            remaining_weight_kg=remaining_weight,
            remaining_volume_m3=remaining_volume,
            remaining_length_cm=remaining_length,
        )

    @staticmethod
    def _check_weight(
        cargo: Cargo, vehicle: VehicleProfile, reasons: list[str], warnings: list[str]
    ) -> int | None:
        if cargo.weight_kg is None:
            warnings.append("Нет данных о весе груза")
            return None
        if cargo.weight_kg > vehicle.cargo_capacity_kg:
            reasons.append(
                f"Превышена грузоподъемность: {cargo.weight_kg} кг > {vehicle.cargo_capacity_kg} кг"
            )
        return vehicle.cargo_capacity_kg - cargo.weight_kg

    @staticmethod
    def _check_volume(
        cargo: Cargo, vehicle: VehicleProfile, reasons: list[str], warnings: list[str]
    ) -> float | None:
        if cargo.volume_m3 is None:
            warnings.append("Нет данных об объеме груза")
            return None
        if cargo.volume_m3 > vehicle.volume_m3:
            reasons.append(
                f"Недостаточный объем кузова: {cargo.volume_m3} м³ > {vehicle.volume_m3} м³"
            )
        return vehicle.volume_m3 - cargo.volume_m3

    @staticmethod
    def _check_dimensions(
        cargo: Cargo, vehicle: VehicleProfile, reasons: list[str], warnings: list[str]
    ) -> int | None:
        if cargo.length_cm is None and cargo.width_cm is None and cargo.height_cm is None:
            warnings.append("Нет данных о габаритах груза")
            return None
        checks = (
            ("длине", cargo.length_cm, vehicle.length_cm),
            ("ширине", cargo.width_cm, vehicle.width_cm),
            ("высоте", cargo.height_cm, vehicle.height_cm),
        )
        for axis, cargo_size, vehicle_size in checks:
            if cargo_size is not None and cargo_size > vehicle_size:
                reasons.append(f"Груз не помещается по {axis}: {cargo_size} см > {vehicle_size} см")
        if cargo.length_cm is None:
            return None
        return vehicle.length_cm - cargo.length_cm

    @staticmethod
    def _check_pallets(cargo: Cargo, vehicle: VehicleProfile, reasons: list[str]) -> None:
        if cargo.pallet_count is not None and cargo.pallet_count > vehicle.pallet_capacity:
            reasons.append(
                f"Не хватает паллетомест: {cargo.pallet_count} > {vehicle.pallet_capacity}"
            )

    @staticmethod
    def _check_body_type(cargo: Cargo, vehicle: VehicleProfile, reasons: list[str]) -> None:
        required = cargo.required_body_type
        if required is not None and required is not vehicle.body_type:
            reasons.append(
                f"Требуется кузов «{required.value}», у автомобиля «{vehicle.body_type.value}»"
            )

    @staticmethod
    def _check_region(cargo: Cargo, vehicle: VehicleProfile, reasons: list[str]) -> None:
        if (
            cargo.loading_region
            and vehicle.allowed_regions
            and cargo.loading_region not in vehicle.allowed_regions
        ):
            reasons.append(f"Регион загрузки «{cargo.loading_region}» вне зоны работы автомобиля")
