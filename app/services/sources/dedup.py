"""Дедупликация грузов: ATI отдаёт один груз многократно (Stage 9.5).

Fingerprint — sha256 от смысловых полей (источник, внешний id, направление,
вес, цена): изменившаяся цена или вес считаются НОВЫМ предложением.
Память ограничена (LRU): дедупликатор живёт процессом, не базой.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum

from app.core.models.cargo_identity import cargo_offer_fingerprint
from app.core.models.logistics.cargo import Cargo

_DEFAULT_CAPACITY = 5000


def cargo_fingerprint(cargo: Cargo) -> str:
    """Отпечаток груза: hash(источник|id|откуда|куда|вес|цена)."""
    return cargo_offer_fingerprint(cargo)


class CargoDeduplicator:
    """Отсев повторных грузов по отпечатку (LRU, ограниченная память)."""

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()

    def register(self, cargo: Cargo) -> bool:
        """Зарегистрировать груз: ``True`` — новый, ``False`` — дубликат."""
        fingerprint = cargo_fingerprint(cargo)
        if fingerprint in self._seen:
            self._seen.move_to_end(fingerprint)
            return False
        self._seen[fingerprint] = None
        if len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return True

    def __len__(self) -> int:
        """Сколько отпечатков в памяти."""
        return len(self._seen)


class DeduplicationStatus(Enum):
    """Вердикт по грузу: новый, дубликат или обновление известного."""

    NEW = "new"
    DUPLICATE = "duplicate"
    UPDATED = "updated"


@dataclass(frozen=True, slots=True)
class DeduplicationVerdict:
    """Результат оценки груза сервисом дедупликации."""

    status: DeduplicationStatus
    changes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """Смысловые поля груза для обнаружения изменений."""

    loading_region: str
    unloading_region: str
    weight_kg: int | None
    price: str  # Decimal сериализуется строкой (стабильное сравнение)

    @classmethod
    def of(cls, cargo: Cargo) -> _Snapshot:
        return cls(
            loading_region=cargo.loading_region,
            unloading_region=cargo.unloading_region,
            weight_kg=cargo.weight_kg,
            price=str(cargo.payment_amount),
        )

    def diff(self, other: _Snapshot) -> tuple[str, ...]:
        """Какие поля изменились (термины события CargoUpdated)."""
        changes: list[str] = []
        if self.price != other.price:
            changes.append("price")
        if (
            self.loading_region != other.loading_region
            or self.unloading_region != other.unloading_region
        ):
            changes.append("route")
        if self.weight_kg != other.weight_kg:
            changes.append("weight")
        return tuple(changes)


class CargoDeduplicationService:
    """Дедупликация с обнаружением ОБНОВЛЕНИЙ (Stage 9.6).

    Идентичность груза — ``source_id|id`` (external id источника). Один и
    тот же груз с той же ценой/маршрутом/весом — дубликат; с изменившимися —
    вердикт UPDATED (пайплайн публикует CargoUpdated и снова ведёт груз в
    подбор). Изменение даты погрузки не отслеживается, пока в Cargo нет
    поля даты (ограничение зафиксировано в ADR-0024).
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, _Snapshot] = OrderedDict()

    def assess(self, cargo: Cargo) -> DeduplicationVerdict:
        """Оценить груз: NEW / DUPLICATE / UPDATED (+ список изменений)."""
        identity = f"{cargo.source_id}|{cargo.id}"
        snapshot = _Snapshot.of(cargo)
        previous = self._seen.get(identity)
        if previous is None:
            self._remember(identity, snapshot)
            return DeduplicationVerdict(status=DeduplicationStatus.NEW)
        self._seen.move_to_end(identity)
        if previous == snapshot:
            return DeduplicationVerdict(status=DeduplicationStatus.DUPLICATE)
        self._seen[identity] = snapshot
        return DeduplicationVerdict(
            status=DeduplicationStatus.UPDATED, changes=previous.diff(snapshot)
        )

    def _remember(self, identity: str, snapshot: _Snapshot) -> None:
        self._seen[identity] = snapshot
        if len(self._seen) > self._capacity:
            self._seen.popitem(last=False)

    def __len__(self) -> int:
        """Сколько грузов в памяти дедупликации."""
        return len(self._seen)
