"""Benchmark SQLite route cache with 100 000 records."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from app.core.models.routes import RouteEstimate
from app.infrastructure.storage import Database, SqliteRouteCacheRepository


async def run(count: int) -> None:
    """Insert and read route cache records."""
    with tempfile.TemporaryDirectory(prefix="logistai-route-cache-") as tmp:
        db_path = Path(tmp) / "routes.db"
        database = Database(db_path)
        database.connect()
        repository = SqliteRouteCacheRepository(database)
        estimate = RouteEstimate(
            distance_km=726.0,
            duration_hours=10.2,
            confidence_score=95,
            provider="yandex",
            provider_label="Яндекс, грузовой маршрут",
            traffic_aware=True,
            has_tolls=True,
            supports_truck_restrictions=True,
            toll_information_available=True,
        )

        started = time.perf_counter()
        for index in range(count):
            await repository.save_route(
                f"benchmark:{index}",
                estimate,
                ttl=timedelta(minutes=45),
            )
        insert_ms = int((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        hits = 0
        now = estimate.calculated_at
        for index in range(0, count, max(1, count // 1000)):
            cached = await repository.get_route(f"benchmark:{index}", now=now)
            if cached is not None:
                hits += 1
        read_ms = int((time.perf_counter() - started) * 1000)
        database.close()

    print(f"Route cache benchmark: {count} records")
    print(f"Insert: {insert_ms} ms")
    print(f"Sample reads: {read_ms} ms")
    print(f"Hits: {hits}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Benchmark SQLite route cache")
    parser.add_argument("--count", type=int, default=100_000)
    args = parser.parse_args()
    asyncio.run(run(args.count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
