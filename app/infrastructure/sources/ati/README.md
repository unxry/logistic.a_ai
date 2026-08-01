# ATI.SU — адаптер источника

Скелет Stage 5.1. Контракт (`AtiSource` → порт `CargoSource`) полностью готов;
реальные запросы к API появятся в Stage 5.2 — изменится только `client.py`.

| Файл | Ответственность |
|---|---|
| `source.py` | `AtiSource`: spec (capabilities, расписание 5 мин, лимит 30 req/min, `enabled=False` — включается конфигурацией пользователя) + `fetch(context)` |
| `client.py` | Транспорт (httpx в 5.2), авторизация по `api_key` из SourceCredentialProvider |
| `mapper.py` | Поля ответа ATI → `RawCargo` (единицы помечаются: тонны/метры/м³); нормализация — НЕ здесь |
| `errors.py` | HTTP-статусы ATI → доменные `SourceError` |

Включение источника (без кода): конфигурация `source_id="ati"` с
`credentials_reference` (секрет `source:<ref>:api_key` в Keychain) и
`enabled=true`.
