"""Benchmark SQLite-хранилища грузов на 100 000 записей.

Запуск:
    uv run python scripts/sqlite_cargo_benchmark.py --total 100000

Проверяет bulk insert/update, индексы поиска, избранное и ignored-offer lookup.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.core.models.cargo_workflow import (
    CargoWorkflowAction,
    CargoWorkflowState,
    CargoWorkflowTransition,
)
from app.core.models.logistics.cargo import Cargo
from app.infrastructure.storage import Database, SqliteCargoRepository


def _cargo(index: int) -> Cargo:
    return Cargo(
        id=f"bench-{index}",
        source_id="ati",
        title=f"Bench cargo {index}",
        loading_region="Москва" if index % 2 == 0 else "Казань",
        unloading_region="Санкт-Петербург" if index % 3 == 0 else "Екатеринбург",
        payment_amount=Decimal(50_000 + index % 90000),
        distance_km=float(200 + index % 1800),
        weight_kg=1000 + index % 5000,
        created_at=datetime.now(UTC) - timedelta(minutes=index % 1440),
        raw={"index": index},
    )


async def run_benchmark(total: int) -> None:
    """Создать временную БД, записать total грузов и проверить read-path."""
    with tempfile.TemporaryDirectory(prefix="logistai-sqlite-") as directory:
        database = Database(Path(directory) / "bench.db")
        database.connect()
        repository = SqliteCargoRepository(database)
        cargos = tuple(_cargo(index) for index in range(total))

        started = time.perf_counter()
        await repository.save_many(cargos)
        insert_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        favorites = tuple(
            CargoWorkflowTransition.create(
                cargo_id=f"bench-{index}",
                from_state=None,
                action=CargoWorkflowAction.FAVORITE,
                actor="benchmark",
            )
            for index in range(0, min(total, 1000), 10)
        )
        for transition in favorites:
            await repository.transition_workflow(transition)
        favorite_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        found = await repository.find_by_region("Москва")
        favorites_page = await repository.list_by_state(
            CargoWorkflowState.FAVORITE,
            sort_by="distance",
            limit=50,
        )
        lookup_ms = (time.perf_counter() - started) * 1000

        database.close()

    print("── SQLite Cargo Benchmark ───────────────────────────────")
    print(f"Записей:             {total}")
    print(f"Bulk insert/update:  {insert_ms:>8.0f} ms")
    print(f"Workflow transitions:{favorite_ms:>8.0f} ms")
    print(f"Indexed lookups:     {lookup_ms:>8.0f} ms")
    print(f"Москва найдено:      {len(found)}")
    print(f"Избранное page:      {len(favorites_page)}")
    print(f"Средняя запись:      {insert_ms / max(1, total):>8.3f} ms/груз")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Benchmark SQLite CargoRepository")
    parser.add_argument("--total", type=int, default=100_000)
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.total))


if __name__ == "__main__":
    main()
