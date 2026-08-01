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
mv pre-commit-config.yaml .pre-commit-config.yaml  # однократно
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

1. **Ключ в Keychain.** Получите личный токен в кабинете ati.su и сохраните
   его в связке ключей под сервисом LogistAI:
   - поле `source:ati_main:api_key` — сам токен
   - (альтернатива: `source:ati_main:login` + `source:ati_main:password` —
     клиент сам получит и будет обновлять сессионный токен)
2. **Конфигурация источника** — `sources.json` рядом с настройками:

   ```json
   {
     "configurations": [{
       "id": "…", "source_id": "ati", "enabled": true,
       "name": "ATI Москва",
       "credentials_reference": "ati_main",
       "polling_interval_seconds": 300,
       "max_results": 100,
       "filters": {
         "regions": "Москва, Московская область",
         "min_weight": "1000",
         "max_weight": "20000"
       },
       "created_at": "2026-07-31T12:00:00+00:00",
       "updated_at": "2026-07-31T12:00:00+00:00"
     }]
   }
   ```

3. **Запуск.** Scheduler стартует вместе с приложением: ATI опрашивается
   каждые `polling_interval_seconds`, найденные грузы проходят дедупликацию,
   поиск и интеллектуальный подбор; лучший груз приходит уведомлением и
   появляется в Hero-карточке дашборда.

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
