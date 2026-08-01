"""CargoPreFilter — быстрый отсев очевидно неподходящих грузов.

НЕ определяет совместимость (это CompatibilityChecker) — только дешёвые
проверки по критериям запроса. Отсутствие данных у груза префильтр НЕ
отбрасывает (кроме явных требований запроса, например min_price).
"""

from __future__ import annotations

from app.core.models.logistics.cargo import Cargo
from app.core.models.search import CargoSearchQuery


class CargoPreFilter:
    """Дешёвые проверки до дорогой оценки совместимости."""

    def passes(self, cargo: Cargo, query: CargoSearchQuery) -> tuple[bool, str]:
        """(прошёл, причина отсева) — причина пуста при прохождении."""
        if query.categories and cargo.category not in query.categories:
            return False, f"Категория «{cargo.category.value}» не входит в запрос"
        if query.regions and cargo.loading_region and cargo.loading_region not in query.regions:
            return False, f"Регион загрузки «{cargo.loading_region}» не входит в запрос"
        if (
            query.required_body_types
            and cargo.required_body_type is not None
            and cargo.required_body_type not in query.required_body_types
        ):
            return False, "Тип кузова груза не входит в запрос"
        weight = cargo.weight_kg
        if query.min_weight_kg is not None and weight is not None and weight < query.min_weight_kg:
            return False, f"Вес {weight} кг меньше минимального"
        if query.max_weight_kg is not None and weight is not None and weight > query.max_weight_kg:
            return False, f"Вес {weight} кг больше максимального"
        if query.min_price is not None:
            if cargo.payment_amount is None:
                return False, "Нет цены, а запрос требует минимальную ставку"
            if cargo.payment_amount < query.min_price:
                return False, f"Ставка {cargo.payment_amount} ниже минимальной"
        distance = cargo.distance_km
        if (
            query.max_distance_km is not None
            and distance is not None
            and distance > query.max_distance_km
        ):
            return False, f"Расстояние {distance:.0f} км больше лимита"
        return True, ""
