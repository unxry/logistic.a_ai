# Production routing

LogistAI считает маршрут через тот же порт `RouteProvider`, который был
подготовлен в Route Intelligence. Рабочая цепочка:

```text
Matching / Profit Calculator
        ↓
RouteService
        ↓
CompositeRouteProvider
        ├── YandexTruckRouteProvider
        ├── OsrmRouteProvider
        └── MockRouteProvider
        ↓
RouteEstimate
        ↓
RouteCostCalculator
        ↓
ProfitAnalysis
```

## Providers

- **Yandex Truck Routing** — основной provider. Использует `mode=truck`,
  координаты, массу, габариты, axle weight и permits, если они указаны в
  профиле машины.
- **OSRM** — approximate fallback. Возвращает distance/duration, но не
  учитывает грузовые ограничения, traffic и стоимость/наличие платных дорог.
- **Mock** — offline/dev и последний аварийный резерв.

## Settings

`settings.json` хранит только routing policy и ссылку на секрет:

```json
{
  "routing": {
    "provider": "auto",
    "yandex_credentials_reference": "yandex_routes",
    "osrm_base_url": "https://router.project-osrm.org",
    "traffic_enabled": true,
    "avoid_tolls": false,
    "avoid_unpaved": false,
    "alternatives_count": 1,
    "cache_enabled": true,
    "fallback_enabled": true
  }
}
```

Yandex API key хранится в Keychain-compatible secret store:

```text
source:yandex_routes:api_key
```

Не коммитьте ключи и не вставляйте их в чат.

## Cache

SQLite cache хранит route estimates и geocoding results. Ключ маршрута
учитывает:

- origin/destination coordinates;
- вес и габариты машины;
- permits;
- `avoid_tolls`, `avoid_unpaved`;
- departure hour bucket;
- provider id.

TTL задаётся `RouteCachePolicy`:

- Yandex traffic-aware: 45 минут;
- Yandex traffic-unaware: 7 дней;
- OSRM: 30 дней;
- geocoding: 90 дней.

Для одинаковых concurrent route requests используется per-key lock: наружу
уходит один HTTP-запрос, остальные получают cache hit.

## Smoke

Демо без сети:

```bash
uv run python main.py --demo-routes
uv run python main.py --demo-routes-smoke  # CI-friendly: вывести smoke и выйти
```

Live smoke с настоящим ключом:

```bash
YANDEX_ROUTER_API_KEY="..." uv run python scripts/yandex_routes_smoke.py
```

Benchmark SQLite route cache:

```bash
uv run python scripts/route_cache_benchmark.py --count 100000
```
