# Архитектура LogistAI

> Живой документ. Обновляется на каждом ревью-гейте этапа.
> Разделы про механизмы этапов 1–5 описывают **целевые контракты** — они
> зафиксированы проектированием и уточняются по мере реализации.
> Ключевые решения с обоснованиями — в [docs/adr/](docs/adr/).

## 1. Что это за приложение

LogistAI — desktop-приложение для логистов (macOS, Apple Silicon): быстро находит
самые выгодные грузы среди множества предложений и уведомляет пользователя.
v0.1 — только инфраструктура (окно, настройки, Telegram, уведомления, журнал);
анализ грузов, AI, расчёт прибыли и источники (ATI и др.) — последующие версии.

Требование №1 к архитектуре: **Windows-версия без переписывания логики** —
меняются только адаптеры инфраструктуры.

## 2. Принципы

1. **Clean Architecture / правило зависимостей** — все стрелки импортов направлены
   к ядру. Ядро не знает ни о Qt, ни о httpx, ни об ОС.
2. **Ports & Adapters** — ядро объявляет контракты (`typing.Protocol`),
   инфраструктура их реализует.
3. **Композиция в одном месте** — все объекты собираются в `app/bootstrap.py`
   (composition root). Никаких глобальных переменных и синглтонов.
4. **Interface Segregation + MVVM** — компонент получает через конструктор только
   то, что ему нужно. Цепочка строго `View → ViewModel → Service`: окно знает
   только свой ViewModel (пример: `MainWindow(view_model)`), контейнер не
   покидает composition root.
5. **Изменения — команды, факты — события, чтение — query**:
   мутации проходят через CommandBus (один обработчик, сквозной аудит),
   свершившиеся факты публикуются в EventBus (много подписчиков),
   чтение — обычные методы сервисов.
6. **Дисциплина автоматизирована** — направление зависимостей охраняет
   import-linter, стиль — ruff, типы — mypy strict, всё валит CI при нарушении.

## 3. Слои

```
┌────────────────────────────────────────────────────────────────┐
│ PRESENTATION · app/ui                                          │
│ MainWindow · Pages · Widgets · Theme · ViewModels (MVVM)       │
└───────────────▲────────────────────────────────────────────────┘
                │ команды в CommandBus, подписка на EventBus,
                │ query-методы сервисов
┌───────────────┴────────────────────────────────────────────────┐
│ APPLICATION · app/services                                     │
│ SettingsService · TelegramService · NotificationService ·      │
│ Scheduler                                                      │
└───────────────▲────────────────────────────────────────────────┘
                │ зависят только от моделей и портов ядра (+шины)
┌───────────────┴────────────────────────────────────────────────┐
│ DOMAIN · app/core — чистый Python (только stdlib)              │
│ models · events · commands · ports (Protocol) · errors         │
└───────────────▲────────────────────────────────────────────────┘
                │ реализуют порты ядра
┌───────────────┴────────────────────────────────────────────────┐
│ INFRASTRUCTURE · app/infrastructure                            │
│ telegram · notifications · settings · storage · logging ·      │
│ system · sources                                               │
└────────────────────────────────────────────────────────────────┘
Сквозные: app/buses (EventBus, CommandBus) · app/plugins ·
          app/bootstrap + app/container (composition root)
```

### Матрица допустимых импортов

| Пакет | Можно | Нельзя |
|---|---|---|
| `app/core` | stdlib | **всё** из `app.*` |
| `app/buses` | `core` | services, infrastructure, ui, plugins, container |
| `app/services` | `core`, `buses` | infrastructure, ui, plugins |
| `app/infrastructure` | `core` | services, ui, plugins |
| `app/ui` | `core`, `services`, `buses` | infrastructure, plugins, container |
| `app/plugins` | `core`, `buses` | services, infrastructure, ui, container |
| `bootstrap`, `container` | всё | — (это composition root) |

Матрица **исполняется машиной**: контракты import-linter в `pyproject.toml`
(`[tool.importlinter]`), команда `uv run lint-imports`, есть в pre-commit и CI.
Ослаблять контракт можно только осознанным решением + ADR.

Следствия матрицы, о которых легко забыть:
- Адаптер инфраструктуры не может звать сервис. Если адаптеру нужна логика
  сервиса (пример: Telegram-канал уведомлений шлёт через TelegramService) —
  в ядре объявляется порт, сервис ему соответствует структурно (Protocol,
  импорт не нужен), адаптер зависит от порта.
- UI не может читать инфраструктуру напрямую (пример: лента логов). Нужен порт
  в ядре (`LogBuffer`), реализация — в infrastructure, инъекция — в bootstrap.
- Плагины получают точки расширения параметром (`register(extensions)`), а не
  импортом реестров.

## 4. Карта каталогов

```
LogistAI/
├── VERSION                  # ЕДИНСТВЕННЫЙ источник версии приложения
├── main.py                  # тонкая точка входа → app.bootstrap.run_app()
├── pyproject.toml           # зависимости, ruff, mypy, pytest, import-linter
├── pre-commit-config.yaml   # git-хуки (переименовать в .pre-commit-config.yaml)
├── app/
│   ├── bootstrap.py         # composition root: сборка, запуск, shutdown
│   ├── container.py         # AppContainer — все зависимости процесса
│   ├── core/                # ДОМЕН (чистый Python)
│   │   ├── models/          #   BuildInfo, Notification, AppSettings, HistoryEntry…
│   │   │   ├── logistics/   #   Cargo, CargoCategory, VehicleProfile, совместимость
│   │   │   │                #   (+ DRAFT-заготовки: Company, Vehicle, Driver…)
│   │   │   └── routes/      #   Route, RouteEstimate, RouteCostPolicy (Stage 8.5)
│   │   ├── events/          #   AppStarted, TelegramStatusChanged, NotificationDispatched…
│   │   ├── commands/        #   SaveSettings, VerifyTelegram, SendNotification…
│   │   ├── ports/           #   NotificationChannel, SettingsRepository, SecretStore,
│   │   │                    #   HistoryRepository, CargoSource, CargoCompatibilityChecker,
│   │   │                    #   Job, PluginExtensions…
│   │   └── errors.py        #   иерархия LogistAIError
│   ├── buses/               # EventBus + CommandBus (+ middleware аудита)
│   ├── services/            # SettingsService, TelegramService, NotificationService
│   │   ├── logistics/       # CargoCompatibilityService (задел под поиск/скоринг)
│   │   ├── presentation/    # DashboardDataService — read-model для UI (Stage 8.6)
│   │   ├── routes/          # RouteCostCalculator, RouteService (Stage 8.5)
│   │   └── scheduler/       # Scheduler + встроенные задачи
│   ├── infrastructure/
│   │   ├── telegram/        # TelegramClient (httpx), RetryPolicy, маппинг ошибок
│   │   ├── notifications/   # каналы: telegram, macos_native (позже email, discord…)
│   │   ├── routes/          # MockRouteProvider; v0.3+: OSRM, Яндекс, Google, HERE
│   │   ├── settings/        # JsonSettingsRepository, KeyringSecretStore
│   │   ├── storage/         # Database (sqlite3, WAL), миграции, SqliteHistoryRepository
│   │   ├── logging/         # setup, RingBufferHandler, EventBusLogHandler
│   │   ├── system/          # пути (platformdirs), автозапуск, BuildInfo-провайдер
│   │   └── sources/ati/     # production ATI: auth, client, mapper, source, demo
│   ├── plugins/             # Plugin (протокол), PluginLoader
│   └── ui/                  # премиальный shell (Stage 9)
│       ├── main_window.py   # сайдбар + страницы + статус-бар + тосты + ⌘K
│       ├── bridge.py        # UiEventBridge: UI-события → Qt-сигналы
│       ├── theme/           # токены дизайн-системы, QSS, motion-паттерны
│       ├── widgets/         # библиотека компонентов (карточки, графики, оверлеи)
│       ├── pages/           # Dashboard, Грузы, Машина, Поиск, Аналитика…
│       └── viewmodels/      # UI-контракты без Qt: карточки, DashboardViewModel,
│                            # UI-события, мок-данные, снапшот-сериализация
├── config/defaults.json     # дефолтные настройки (шаблон первой записи)
├── docs/                    # adr/, architecture/, development/, roadmap/
├── resources/icons/         # SVG-иконки
├── tests/                   # unit/, ui/ (offscreen)
└── .github/workflows/ci.yml # ruff · mypy · import-linter · pytest (Linux + macOS)
```

## 5. Ключевые механизмы

### 5.1 Composition root
`bootstrap.build_container()` создаёт всё в правильном порядке:
пути → логирование → настройки → шины → хранилище → сервисы →
каналы/источники/плагины → планировщик. `run_app()` запускает Qt + qasync
и организует graceful shutdown (событие `AppClosing` → отмена задач →
закрытие httpx и БД → flush логов).

### 5.2 EventBus и CommandBus
- **EventBus**: `subscribe(EventType, handler)` / `publish(event)`. События —
  frozen dataclasses из `core/events` (время UTC проставляется автоматически).
  Семантика: подписка на конкретный тип (иерархия событий не разворачивается),
  порядок доставки = порядку подписки, повторная подписка того же обработчика —
  ошибка, ошибка подписчика логируется и не мешает остальным. Благодаря qasync
  всё в одном потоке.
- **CommandBus**: `register(CommandType, handler)` — ровно один обработчик
  (дубль — ошибка); `await dispatch(command)` возвращает типизированный
  результат (`Command[R] → R`). Аудит: шина логирует имя типа команды и
  длительность — НИКОГДА не поля (в них бывают секреты). Полноценный
  middleware-конвейер добавим при втором сквозном сценарии.

### 5.3 Настройки и секреты (ADR-0010)
Типизированная модель `AppSettings` (+ `schema_version`, + `vehicle.profiles` —
профили транспорта живут здесь до появления SQLite-репозитория). JSON-файл в
`~/Library/Application Support/LogistAI/`: атомарная запись (tmp →
`os.replace`), **карантин** битого файла (`settings.broken-<время>.json` —
данные пользователя не теряются никогда), цепочка миграций `schema_version`
(каждая обязана поднять версию ровно на 1 — проверяется движком), толерантный
парсинг (мусор в поле → дефолт поля, битый профиль → пропуск).
`SettingsService` не знает о JSON — только порты; изменения — командой
`SaveSettings`; публикует `SettingsChanged`/`ErrorOccurred`.
Секреты (Bot Token) — только в Keychain через `keyring` (порт `SecretStore`,
константы имён секретов — в ядре); в plain JSON секретам нельзя по построению.
`NullSecretStore` — для тестов.

### 5.4 История событий (журнал)
`HistoryEntry(id, ts, kind, level, title, details)`,
`kind ∈ {NOTIFICATION, ERROR, SOURCE_EVENT, USER_ACTION, SYSTEM_EVENT}`.
Хранение — SQLite (WAL). Пишут: NotificationService, обработчик ошибок,
запуск/выход, сохранение настроек. Дашборд и страница журнала читают отсюда.
Чистка по retention — задача планировщика.

### 5.5 Логирование (ADR-0011)
stdlib `logging`, один вызов `setup_logging()` в composition root
(идемпотентен). Три получателя: файл `app.log` с ротацией
(`~/Library/Logs/LogistAI/`), кольцевой буфер на 2000 записей (реализует порт
`LogBuffer` — страница «Логи» читает через порт), `EventBusLogHandler` →
событие `LogRecordAdded` (через порт `EventPublisher`, с защитой от рекурсии
лог→событие→лог). Каждую строку лога в SQLite не пишем — журнал событий и
диагностические логи разделены. `print()` запрещён.

### 5.6 Scheduler Runtime (ADR-0014)

Двигатель платформы: позже запускает ATI Monitor, Cargo Search, плагины,
чистку, бэкапы — без изменения архитектуры.

```
JobRegistry (register без if-ов) ──▶ SchedulerRuntime
   супервизор на задачу: schedule.next_run_at → WAITING → _execute
   _execute: лимит параллельности (JobSkipped) → JobContext(trace_id!)
             → watchdog (asyncio.wait_for по timeout) → JobRetryPolicy
             → метрики → журнал (SYSTEM_EVENT) → события JobStarted/
               Completed/Failed → при ошибке NotificationSender.send(...)
```

Порт `Job` = `spec: JobSpec` (данные: schedule, timeout, retry,
max_parallel_runs) + `run(context)` — исполнитель заменяем без изменения
задач. Политики: `RunOnce`, `Interval` (джиттер); `Cron`/`Adaptive` —
заготовки. `JobContext` несёт logger, notifications (порт), history,
settings-провайдер, trace_factory, clock — задачи не импортируют сервисы.
Управление командами: Start/StopScheduler, Pause/ResumeJob, RunJobNow.
Состояния: IDLE/WAITING/RUNNING/FAILED/PAUSED/STOPPED; метрики — frozen-снапшоты.

### 5.7 Плагины
Протокол `Plugin`: `manifest` (id, name, version, api_version) +
`register(extensions: PluginExtensions)`. `PluginExtensions` (порт ядра) даёт
колбэки: `add_source(...)`, `add_channel(...)`, `add_job(...)`.
`PluginLoader` сканирует `~/Library/Application Support/LogistAI/plugins/`,
проверяет api_version, изолирует ошибки (сломанный плагин → ERROR в журнал,
приложение живёт). Плагин — исполняемый код: доверие на пользователе.

### 5.8 Cargo Sources Framework (ADR-0015)

```
Scheduler ──▶ SourcePollJob (source:<id>, расписание из spec)
                   │
             SourceRuntime — таймаут+ретраи (политики из SourceSpec),
                   │          здоровье (ONLINE/DEGRADED/FAILED/DISABLED),
                   │          метрики, журнал SOURCE_EVENT (trace_id)
             SourceRegistry ──▶ ATI API · Browser · CSV · плагины (Stage 5.1+)
                   │  fetch(context) → SourceResult(RawCargo…)
             CargoNormalizer — кг/тонны, см/метры, м³, категории, кузов, регионы
                   │
              Cargo (домен) ──▶ событие CargoReceived ──▶ Search Engine (Stage 6)
                   └──▶ при ошибке: NotificationSender → Notification Center
```

Порт `CargoSource` = `spec: SourceSpec` (+`SourceCapabilities` — 9 флагов,
по ним Stage 6 поймёт доступные фильтры) + `fetch(context) → SourceResult`.
**Конфигурация пользователем, не кодом (ADR-0016)**: `SourceConfiguration`
(sources.json; секреты — только `credentials_reference` →
`SourceCredentialProvider` поверх Keychain, ключ `source:<ref>:<field>`)
имеет приоритет над заводским spec; скелеты реальных источников поставляются
`enabled=False`. Rate limit — token bucket по `SourceRateLimitPolicy` +
уважение `retry_after`. Каталог для UI — `list_available_sources()`.
ATI-скелет: `infrastructure/sources/ati/` (source/client/mapper/errors) —
Stage 5.2 меняет только client.py.
Источник не знает HTTP/браузер/БД (детали его инфраструктуры), не шлёт
уведомления и не пишет журнал — всё делает runtime. Непарсибельные значения
нормализатор превращает в None — совместимость предупредит, а не отбросит.

### 5.9 Notification Center (ADR-0013)

Единственная операция для любого модуля: `await notification_service.send(n)` —
модуль не знает ни о Telegram, ни о macOS, ни о SQLite, ни об очередях.

```
любой модуль ──▶ NotificationService (очередь + оркестрация, события lifecycle)
                      │ route()
                      ▼
                NotificationRouter (ВСЕ правила выбора каналов)
                      │ dispatch(n, channels)
                      ▼
              NotificationDispatcher ──▶ FormatterRegistry (текст канала)
                      │ asyncio.gather, изоляция ошибок
                      ▼
                ChannelRegistry ──▶ telegram · macos_native · (email, discord…)
                      │
                      ├──▶ HistoryRepository (журнал, trace_id)
                      └──▶ EventBus: Queued → Sending → Delivered | Failed
```

Модель: `NotificationCategory`, `NotificationAction` (кнопки), `payload`,
`NotificationContext` с **trace_id** (сквозная корреляция до журнала),
`NotificationBuilder` (fluent). Каналы — чистый транспорт
(`send(notification, text)`, текст готовит форматтер); Telegram — обычный
consumer (RateLimiter внутри канала), новый канал/форматтер = класс +
регистрация в bootstrap или плагином.

### 5.10 Версия и BuildInfo
Файл `VERSION` — единственный источник. `pyproject.toml` читает его через
hatchling (`dynamic = ["version"]`), приложение — через
`app.infrastructure.system.build_info.load_build_info()` →
`BuildInfo(version, build_date, git_commit, mode)`. Дата и коммит заполняются
скриптом упаковки; режим — env `LOGISTAI_MODE` (`debug`/`release`).
Хардкод версии где-либо ещё — нарушение.

### 5.11 Транспорт и совместимость грузов

Главная ценность продукта — «найди груз под мой автомобиль», поэтому это
домен, а не деталь поиска (ADR-0009). `VehicleProfile` (тип ТС, кузов,
грузоподъёмность, габариты, объём, паллетоместа, регионы) + `CargoCategory` +
расширенный `Cargo` (физические параметры опциональны: нет данных →
предупреждение, не отказ). Порт `CargoCompatibilityChecker`; эталонные правила —
`BasicCompatibilityChecker` в ядре (чистая функция: вес, объём, габариты,
паллеты, кузов, регион; score 0–100). `CargoCompatibilityService` — задел
application-слоя (DI checker'а); выбор активного профиля и батч-проверки
придут с источниками (v0.2).

### 5.12 Telegram-подсистема (ADR-0012, ADR-0025)

Порт `TelegramApi` в ядре (+`TelegramApiFactory`); httpx-клиент — адаптер:
один `AsyncClient`, таймауты 5/10/10/5, RetryPolicy (429 → retry_after;
5xx/сеть → экспонента с джиттером; 400/401/403/404 без повторов), все ошибки
→ доменные `TelegramError`. `TelegramService`: машина состояний
(`TelegramStatusChanged`), `verify()` getMe→getChat→тест на временном клиенте,
очередь отправки (`asyncio.Queue` + воркер + RateLimiter 1 с) с событиями
`NotificationDispatched`/`NotificationFailed`; `send_notification(Notification)`
готов для NotificationService (этап 3.5). Строки собирает
`TelegramNotificationFormatter`/`MessageBuilder` (HTML, автоэкранирование) за
generic-портом `NotificationFormatter`. Секреты: httpx-логгеры приглушены,
сообщения ошибок санитизируются, токен/chat_id в логах запрещены (тесты).

### 5.14 Search Engine (ADR-0017)

```
CargoRepository ──▶ CargoMatchingService (события + уведомление о лучшем)
                          │
                    CargoSearchEngine (чистый, sync):
                    PreFilter → CompatibilityService → ScoreCalculator → Ranking
                          │
                    SearchResult (best, ranking 1..N, trace_id)
```

Скоринг v1: 40% совместимость · 20% ставка руб/км · 20% плечо · 10% свежесть ·
10% категория; несовместимый = 0; деньги — Decimal. Каждый шаг пайплайна —
заменяемый класс. `Cargo.created_at` — момент получения из источника.

### 5.15 Intelligent Matching (ADR-0018, ADR-0020)

Асинхронный слой над Search Engine: `IntelligentMatchingService.select_best(
matches, MatchingContext)` → final_score (30% совместимость · 30% прибыль
(ProfitAnalysis, Decimal) · 20% эффективность маршрута (RouteScoreCalculator
поверх RouteEstimate) · 10% предпочтения (PreferenceEngine, DriverProfile;
запрещённый регион = отказ) · 10% свежесть (общая кривая ядра)) +
**explanation** — человекочитаемые причины. Веса — `MatchingWeights` из
настроек (валидация: сумма 1.0). Каждое решение — MatchingDecision (с
фактической дистанцией маршрута) + события (BestCargoSelected,
CargoRejectedByPreference, MatchingDecisionCreated, ProfitCalculated) —
фундамент обучения. Лучший груз уходит уведомлением категории **ROUTE**
с полной экономикой: расстояние, доход, расходы, чистая прибыль, ₽/км.

### 5.16 Monitoring & Analytics (ADR-0019)

События платформы → `AnalyticsCollector` (счётчики, включая маршруты и ₽/км)
+ `DecisionPersister` (MatchingDecision → SQLite, схема v3, порт
`MatchingRepository`). `summarize_decisions` / `summarize_routes` — чистые
агрегации в ядре (топ причин отказов, лучшие/худшие направления, средняя
прибыль и дистанция). `SourceHealthMonitor` — «⚠️ источник недоступен
N минут» однократно до восстановления. `DailyAnalyticsReportJob` — «Отчёт
LogistAI» через Scheduler и Notification Center.

### 5.17 Route Intelligence (ADR-0020)

```
RouteProvider (порт, async) ──▶ RouteService ──▶ RouteEstimate
  MockRouteProvider │ OSRM │        │ кэш, RouteCalculated, синтетика
  Яндекс │ Google │ HERE            ▼
                              RouteCostCalculator (RouteCostPolicy из настроек)
                                    ▼
                              CargoProfitCalculator → ProfitAnalysis
```

Разделение обязанностей: провайдер знает **геометрию** (расстояние, время,
уверенность, платные участки — если API их отдаёт), деньги досчитывает
`RouteCostCalculator` по тарифам пользователя (`settings.routing`): топливо
(формула ТЗ «км / расход(км/л) × цена» в точной Decimal-форме «литры × цена»),
платные ₽/км, обслуживание ₽/км, водитель ₽/ч. Холостой подгон = топливо +
износ по маршруту «текущая точка → загрузка». Направление неизвестно —
синтетическая оценка по расстоянию из объявления (confidence 40, событие не
публикуется). Эталон дефолтов: Москва → Санкт-Петербург, 710 км / 10 ч →
14 910 + 6 390 + 7 100 + 6 600 = 35 000 ₽ расходов; при доходе 120 000 ₽ —
85 000 ₽ чистыми, 120 ₽/км, 8 500 ₽/ч.

### 5.18 UI-контракты: presentation-слой без Qt (ADR-0021)

```
доменные события ──▶ DashboardViewModel ──▶ UI Event Stream:
(Telegram, Sources,      │  порт DashboardDataProvider      DashboardUpdated
 CargoReceived…)         │  (живой: DashboardDataService,   CargoRecommendationChanged
                         ▼   мок: MockDashboardDataProvider) SourceStatusChanged
                   карточные ViewModel (готовые строки + числа)
```

`app/ui/viewmodels` — контракт для UI-агента: карточки (CargoCardViewModel,
SourceStatusViewModel, AnalyticsViewModel, VehicleViewModel, EventRow…),
StatusBadge со светофорным тоном, DashboardSnapshot, три UI-события и мок
с красивыми детерминированными данными. Правило «ViewModel не знает Qt и
конкретные слои (только ядро)» закреплено СЕДЬМЫМ контрактом import-linter
и subprocess-тестом; форма данных зафиксирована золотыми снапшотами
(`tests/snapshots/*.json`, обновление — `LOGISTAI_UPDATE_SNAPSHOTS=1`).
Живой адаптер порта — `app/services/presentation/DashboardDataService` —
удовлетворяет протокол структурно, не импортируя ui.

### 5.19 Премиальный UI-shell (ADR-0022)

Дизайн-система: `docs/design-system.md` ↔ `app/ui/theme/tokens.py`
(синхронизация охраняется тестом); глобальный QSS и motion-паттерны
(materialize, count-up, lift, pulse) — `app/ui/theme`. Библиотека
компонентов `app/ui/widgets` (Button, GlassCard/HoverCard, Badge,
StatusIndicator, MetricCard, Sparkline, ScoreRing, Timeline, Modal, Toast,
CommandPalette ⌘K, Sidebar, FlowLayout, HeroCard, CargoCardWidget…) и
страницы `app/ui/pages` строятся ТОЛЬКО на токенах и viewmodels; данные
приходят через `UiEventBridge` (UI-события → Qt-сигналы). Петля — qasync
(ADR-0003 исполнен); `--demo` — интерфейс на мок-данных с «оживающим» hero.

### 5.20 ATI Integration и конвейер рекомендаций (ADR-0023)

```
ATI API ──▶ AtiAuthProvider ──▶ AtiClient ──▶ AtiMapper ──▶ RawCargo
(или MockTransport в --demo-ati)                              │
CargoNormalizer ◀─────────────────────────────────────────────┘
      │ Cargo
SourceRuntime ──CargoReceived──▶ RecommendationPipeline:
      дедуп (fingerprint LRU) → CargoRepository → Search Engine →
      Intelligent Matching → Notification (ROUTE) → карточки в Dashboard
```

Весь ATI живёт в `infrastructure/sources/ati/` (auth, client, mapper,
source, demo); секреты — только через SourceCredentialProvider → Keychain.
Клиент повторяет только транспортные сбои; политику опроса (ретраи, 429,
token-bucket) ведёт SourceRuntime. Scheduler стартует вместе с приложением:
ATI-POLL (интервал из конфигурации) + минутный SourceHealthCheckJob.
`--demo-ati` гоняет боевой конвейер на httpx.MockTransport без сети.
Production-надёжность (ADR-0024): CargoDeduplicationService (дубли и
ОБНОВЛЕНИЯ → событие CargoUpdated), NotificationCooldownPolicy (окно 180 с +
«🟢 восстановлен»), production-метрики SourceHealth (₽/ч, доли ошибок и
дублей) и нагрузочная валидация: 1000 грузов ≈ 365 мс / 3.5 МиБ
(`scripts/cargo_pipeline_benchmark.py`).

## 6. Рецепты расширения

### Как добавить Notification Channel (например, Discord)
1. Класс `DiscordChannel` в `app/infrastructure/notifications/discord.py`,
   реализует порт `NotificationChannel` (`id = "discord"`, `async send(...)`).
2. Секреты (webhook-URL) — через `SecretStore`, настройки — поле в `AppSettings`.
3. Регистрация: одна строка в `bootstrap` (или через плагин).
4. Включение: id канала в `settings.notifications.enabled_channels`.
5. Тесты: unit на канал (фейковый транспорт) + тест маршрутизации сервиса.
**Ядро и NotificationService не меняются.**

### Как добавить Source (например, ATI API)
1. `app/infrastructure/sources/ati_api.py`: класс `AtiApiSource(BaseSource)`,
   реализует `CargoSource.fetch()` → нормализация в `core.models.logistics.Cargo`.
2. Ошибки — только доменные (`SourceError` и наследники), сырые httpx-исключения
   наружу не выходят.
3. Регистрация в `SourceRegistry` (bootstrap или плагин).
4. События жизненного цикла (`SOURCE_EVENT`) публикует `BaseSource` — наследник
   получает это бесплатно.
5. Тесты: httpx.MockTransport с записанными ответами.

### Как добавить фоновую задачу (Job)
1. Класс в `app/services/scheduler/jobs/` (или в плагине), реализует порт `Job`.
2. Задача идемпотентна и коротка; долгие операции разбиваются.
3. Исключения не глотать — Scheduler сам запишет их в журнал.
4. Регистрация: `scheduler.add(job)` в bootstrap / `extensions.add_job(job)` в плагине.
5. Интервал — из `AppSettings`, не хардкодом.

### Как добавить Plugin
1. Каталог `~/Library/Application Support/LogistAI/plugins/<имя>/plugin.py`.
2. Класс `MyPlugin` с `manifest` (id, name, version, api_version) и
   `register(extensions)` — внутри только вызовы `extensions.add_*`.
3. Совместимость: api_version плагина должен входить в поддерживаемый диапазон
   приложения, иначе плагин не загружается (запись в журнал).
4. Плагин импортирует только `app.core` (и `app.buses` при необходимости).

### Как добавить команду / событие
1. Frozen dataclass в `core/commands` (намерение) или `core/events` (факт).
2. Обработчик команды — в соответствующем сервисе; регистрация пары
   «тип → обработчик» в bootstrap.
3. UI диспатчит команду через CommandBus, о результате узнаёт по событию.
4. Прямые вызовы сервис → сервис для мутаций запрещены — только через шину.

### Как добавить страницу UI
1. `app/ui/pages/<name>_page.py` (виджеты, ноль логики) +
   `app/ui/viewmodels/<name>_viewmodel.py` (QObject: состояние, сигналы,
   подписки на EventBus, команды, query-вызовы).
2. ViewModel получает зависимости конструктором (bootstrap собирает).
3. Регистрация страницы в MainWindow/Sidebar.
4. Тесты: логика — на ViewModel без виджетов; смоук страницы — pytest-qt offscreen.

## 7. Что запрещено

1. Нарушать матрицу импортов (§3) — валит CI.
2. Глобальные переменные, синглтоны, `QApplication.instance()` в логике.
3. Бизнес-логика в виджетах; обращение View напрямую к сервисам.
4. `print()` вместо `logging`.
5. Секреты в коде, JSON или логах — только `SecretStore`.
6. Сырой SQL вне `infrastructure/storage`.
7. Молча проглоченные исключения (`except: pass`).
8. Хардкод версии, путей ОС, интервалов — всё из `VERSION`/`PathProvider`/настроек.
9. God objects и файлы-«портянки» (ориентир ≤ 300 строк).
10. `# type: ignore` и ослабление контрактов import-linter без обоснования и ADR.

## 8. Тестирование

- **unit** (`tests/unit`) — ядро, шины, сервисы (порты подменяются фейками),
  репозитории (`tmp_path`), Telegram-клиент (httpx.MockTransport).
- **ui** (`tests/ui`) — pytest-qt, offscreen; логика — в тестах ViewModel.
- Фейки предпочтительнее моков: фейк-реализация порта переживает рефакторинг.
- CI гоняет всё на Linux (offscreen) и тесты на macOS (целевая платформа).

## 9. Кроссплатформенность (план Windows-порта)

| Заменяется | macOS (сейчас) | Windows (потом) |
|---|---|---|
| Секреты | Keychain (keyring) | Credential Manager (тот же keyring) |
| Нативные уведомления | UNUserNotificationCenter / osascript | WinRT toasts |
| Автозапуск | LaunchAgent plist | ключ реестра Run |
| Пути | platformdirs | platformdirs (без изменений) |

Ядро, сервисы, шины, UI (Qt), хранилище — без изменений.

## 10. Указатель ADR

| ADR | Решение |
|---|---|
| [0001](docs/adr/0001-clean-architecture.md) | Clean Architecture + Ports & Adapters |
| [0002](docs/adr/0002-pyside6.md) | PySide6 как GUI-фреймворк |
| [0003](docs/adr/0003-qasync.md) | qasync: одна петля asyncio + Qt |
| [0004](docs/adr/0004-event-bus.md) | Собственный EventBus |
| [0005](docs/adr/0005-command-bus.md) | CommandBus для мутаций |
| [0006](docs/adr/0006-repository-pattern.md) | Repository Pattern |
| [0007](docs/adr/0007-sqlite.md) | SQLite (stdlib sqlite3) |
| [0008](docs/adr/0008-keychain-secrets.md) | Секреты в Keychain (keyring) |
| [0009](docs/adr/0009-vehicle-profile-and-cargo-compatibility.md) | Профиль транспорта и совместимость грузов |
| [0010](docs/adr/0010-settings-and-secret-storage.md) | Хранение настроек и секретов |
| [0011](docs/adr/0011-logging-architecture.md) | Архитектура логирования |
| [0012](docs/adr/0012-telegram-architecture.md) | Архитектура Telegram-подсистемы |
| [0013](docs/adr/0013-notification-center.md) | Notification Center |
| [0014](docs/adr/0014-scheduler-runtime.md) | Scheduler Runtime |
| [0015](docs/adr/0015-cargo-sources-framework.md) | Cargo Sources Framework |
| [0016](docs/adr/0016-source-configuration.md) | Конфигурация источников, учётки, rate limits |
| [0017](docs/adr/0017-search-engine.md) | Search Engine и модель скоринга |
| [0018](docs/adr/0018-intelligent-matching.md) | Intelligent Matching: предпочтения, прибыль |
| [0019](docs/adr/0019-monitoring-analytics.md) | Monitoring & Analytics |
| [0020](docs/adr/0020-route-intelligence.md) | Route Intelligence: маршруты и экономика рейса |
| [0021](docs/adr/0021-ui-contracts.md) | UI-контракты: presentation-слой без Qt |
| [0022](docs/adr/0022-premium-ui.md) | Премиальный UI: дизайн-система, shell, qasync |
| [0023](docs/adr/0023-ati-integration.md) | ATI Integration: production-источник грузов |
| [0024](docs/adr/0024-ati-production-reliability.md) | ATI Production Reliability |
| [0025](docs/adr/0025-production-telegram.md) | Production Telegram: бот, шаблоны, inline-кнопки |
