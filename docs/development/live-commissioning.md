# Live commissioning checklist

Stage 10.2 не считается завершённым только по HTTP 200. Нужен факт:
`Real cargo received > 0`.

## ATI live/demo matrix

| Component | Live implementation | Demo implementation | `main.py` | `--demo` | `--demo-ati` | tests |
|---|---|---|---|---|---|---|
| ATI client | `AtiClient` | `build_demo_ati_client()` mock transport | live | off | demo ATI transport | both |
| ATI source | `AtiSource` | same `AtiSource` with demo client/credentials | live | off | demo | both |
| ATI credentials | `KeychainSourceCredentialProvider` | `DemoAtiCredentialProvider` | Keychain | no | demo provider | fake stores |
| Source config | `JsonSourceConfigurationRepository` | `DemoAtiConfigurationRepository` | live `sources.json` | no | demo config | fake/demo repos |
| Dashboard data | `DashboardDataService` | `MockDashboardDataProvider` | live | demo dashboard | live pipeline | both |
| Cargo storage | `SqliteCargoRepository` | in-memory only in unit tests | SQLite | SQLite | SQLite | both |
| Routing | `CompositeRouteProvider` | demo Yandex mock only for `--demo-routes` | Yandex→OSRM→Mock fallback | same | same | mock/httpx |
| Telegram | `TelegramService` + `TelegramClient` | fake APIs in tests | Keychain | Keychain unless disabled | Keychain unless disabled | fake APIs |

Normal launch `uv run python main.py` must not use:

- `build_demo_ati_client()`;
- `DemoAtiConfigurationRepository`;
- `DemoAtiCredentialProvider`;
- `MockDashboardDataProvider`;
- fixture/static cargo providers.

`MockRouteProvider` is allowed only as the last routing fallback and must be
visible through route metadata: `provider="mock"`, `is_fallback=True`, low
confidence.

## Official ATI access conclusion

ATI documentation states that the carrier API searches loads only on Personal
Boards, not the General ATI.SU marketplace. Therefore `GET
/v1.0/loads/search/byboards` proves market data only if the current account has
`canView`/participating boards and those boards contain loads.

Run:

```bash
uv run python scripts/ati_access_diagnostics.py
uv run python scripts/ati_live_smoke.py --no-filters
uv run python scripts/ati_live_smoke.py --minimal-filters
uv run python scripts/ati_live_smoke.py --vehicle-filters
uv run python scripts/live_end_to_end.py --dry-run
uv run python scripts/live_end_to_end.py
```

If all live ATI endpoints return count `0`, the correct report wording is:

> LogistAI готов обрабатывать реальные грузы, но текущий ATI API access не
> предоставляет рыночную выдачу.

Do not claim that LogistAI receives real ATI cargo until `Real cargo received`
is greater than zero.
