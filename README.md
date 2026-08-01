# LogistAI

Интеллектуальный помощник логиста для macOS (Apple Silicon).
Находит самые выгодные грузы среди большого количества предложений и уведомляет
пользователя (Telegram, нативные уведомления macOS).

**Статус:** v0.1 (alpha) — инфраструктура. Версия — в файле [`VERSION`](VERSION)
(единственный источник, читается приложением через `BuildInfo`).

## Стек

Python 3.13+ · PySide6 · qasync · httpx · SQLite · platformdirs · keyring

## Документация

| Документ | Что внутри |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Как устроена архитектура, куда добавлять код, что запрещено, рецепты расширения |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Стиль кода, правила ревью, процесс этапов |
| [docs/adr/](docs/adr/) | Architecture Decision Records — почему приняты ключевые решения |
| [docs/development/](docs/development/) | Настройка окружения, команды |
| [docs/routing.md](docs/routing.md) | Production routing: Yandex Truck, OSRM fallback, cache, smoke |
| [docs/roadmap/](docs/roadmap/) | План версий |
| [LICENSE](LICENSE) | Проприетарная лицензия |

## Разработка

```bash
uv sync                                            # зависимости (+dev)
uv run pre-commit install                          # git-хуки (однократно, обязательно)
uv run python main.py          # запуск приложения
uv run python main.py --demo-routes  # demo-smoke маршрута Yandex Truck
uv run pytest                  # тесты
uv run ruff format .           # форматирование
uv run ruff check .            # линтер
uv run mypy                    # типы (strict)
uv run lint-imports            # архитектурные контракты
```

CI (GitHub Actions) прогоняет всё то же самое на каждом push / pull request:
Linux (полный набор проверок) + macOS (тесты на целевой платформе).

## Telegram-бот

Полная настройка бота (BotFather, команды, описание, безопасность) —
[docs/telegram-botfather.md](docs/telegram-botfather.md). После ввода токена
и Chat ID бот отвечает на /status, /search, /report, /settings, а лучшие
грузы приходят с кнопками «Открыть ATI · Подробнее · Игнорировать».

## Как подключить ATI

Секреты живут ТОЛЬКО в Keychain (macOS) — не в JSON и не в коде.

1. **ATI credentials.** Получите официальный временный ATI token и сохраните
   его интерактивно:

   ```bash
   uv run python scripts/store_ati_credentials.py
   ```

   Скрипт пишет только в Keychain:
   `source:ati_main:client_id`, `source:ati_main:access_token`,
   `source:ati_main:token_expires_at`; в выводе — только маскированные значения.
2. **Telegram credentials.** Сохраните Bot Token и Chat ID так же через Keychain:

   ```bash
   uv run python scripts/configure_live_credentials.py  # единый ATI+Telegram+Yandex setup
   uv run python scripts/store_telegram_credentials.py
   uv run python scripts/telegram_smoke.py
   ```

3. **Конфигурация источника** — `sources.json` рядом с настройками:

   ```json
   {
     "configurations": [{
       "id": "…", "source_id": "ati", "enabled": true,
       "name": "ATI Live",
       "credentials_reference": "ati_main",
       "polling_interval_seconds": 300,
       "max_results": 100,
       "filters": {
         "api_mode": "byboards",
         "max_weight": "6000",
         "cargo_types": "тент"
       },
       "created_at": "2026-07-31T12:00:00+00:00",
       "updated_at": "2026-07-31T12:00:00+00:00"
     }]
   }
   ```

   `byboards` использует официальный carrier endpoint для персональных площадок.
   Общая площадка ATI.SU через этот API не выдаётся; если аккаунт не состоит
   в персональной площадке и не имеет своих грузов, live-smoke честно вернёт
   `Received: 0`.

4. **Запуск.** Scheduler стартует вместе с приложением: ATI опрашивается
   каждые `polling_interval_seconds`, найденные грузы проходят дедупликацию,
   поиск и интеллектуальный подбор; лучший груз приходит уведомлением и
   появляется в Hero-карточке дашборда.

Live-проверка без раскрытия секретов:

```bash
uv run python scripts/ati_access_diagnostics.py
uv run python scripts/ati_live_smoke.py
uv run python scripts/live_end_to_end.py --dry-run
```

Проверить весь конвейер без ключей и сети:

```bash
uv run python main.py --demo-ati
```

В журнале появится чек-лист: «ATI подключен 🟢 → получено N грузов →
лучший груз найден → AI Score рассчитан → уведомление отправлено».
Эндпоинты и маппинг полей боевого API собраны константами в
`app/infrastructure/sources/ati/{client,mapper}.py` (см. ADR-0023).

## Маршруты

Production routing использует цепочку Yandex Truck → OSRM → Mock через
существующий порт `RouteProvider`. Yandex API key хранится только в SecretStore
по ссылке `source:yandex_routes:api_key`; в JSON сохраняется только
`yandex_credentials_reference`.

```bash
uv run python main.py --demo-routes
uv run python main.py --demo-routes-smoke
YANDEX_ROUTER_API_KEY="..." uv run python scripts/yandex_routes_smoke.py
uv run python scripts/route_cache_benchmark.py --count 100000
```

Подробнее: [docs/routing.md](docs/routing.md).

## Структура

| Пакет | Назначение |
|---|---|
| `app/core` | Домен: модели (вкл. историю событий и DRAFT-модели логистики), события, команды, порты, ошибки. Без внешних зависимостей |
| `app/buses` | EventBus (факты) и CommandBus (намерения) |
| `app/services` | Сервисы приложения: настройки, Telegram, уведомления, планировщик |
| `app/infrastructure` | Адаптеры: Telegram API, каналы уведомлений, JSON/Keychain, SQLite, логирование, ОС, источники грузов |
| `app/plugins` | Система плагинов: новые источники, каналы, задачи |
| `app/ui` | PySide6: окна, страницы, виджеты, тема, ViewModel'и (MVVM) |

Правило зависимостей: `ui → services → core ← infrastructure` — закреплено
контрактами import-linter, нарушение валит CI.
Изменения — через команды, факты — через события, чтение — query-методами сервисов.
