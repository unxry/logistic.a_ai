# Roadmap LogistAI

> Ориентир, а не обещание. Уточняется на ревью-гейтах.
> Порядок headless-first подтверждён владельцем 2026-07-31: сначала вся
> серверная архитектура, UI — один раз поверх готовых движков.

## v0.1 — headless-ядро платформы

| Этап | Содержимое | Статус |
|---|---|---|
| 0 | Каркас: pyproject, структура пакетов, окно-заглушка | ✅ |
| 0.5 | Инженерная база: import-linter, CI, pre-commit, ADR, VERSION+BuildInfo | ✅ |
| 1 | Ядро: модели, события, команды, порты, EventBus, CommandBus | ✅ |
| 1.5 | Домен транспорта: VehicleProfile, категории, совместимость | ✅ |
| 2 | Настройки (JSON+миграции+карантин), секреты (Keychain), логирование | ✅ |
| 3 | Telegram production-ready: клиент, ретраи, машина состояний | ✅ |
| 3.5 | Notification Center: Router/Dispatcher/Registries, SQLite-журнал, trace_id | ✅ |
| 4 | Scheduler Runtime: JobSpec/политики/ретраи/watchdog/метрики/команды | ✅ |

## v0.2 — поиск грузов (headless)

| Этап | Содержимое | Статус |
|---|---|---|
| 5 | Cargo Sources Framework: SourceSpec/Capabilities, RawCargo→Normalizer→Cargo, SourceRuntime, здоровье/метрики | ✅ |
| 5.1 | Конфигурация источников (sources.json + Keychain-учётки + rate limits) + скелет ATI | ✅ |
| 5.2 | Реальные источники: ATI API — ✅ выполнено этапом 9.5; ATI Browser, Ozon, WB, CSV (+PluginLoader) | ◐ |
| 6 | Cargo Search Engine: PreFilter → Compatibility → Scoring → Ranking, CargoRepository, события, уведомление о лучшем | ✅ |
| 7 | Intelligent Matching v1: DriverProfile, прибыль (Decimal), маршрутный фактор, объяснимый выбор, MatchingDecision | ✅ |
| 8 | Monitoring & Analytics: решения в SQLite, счётчики из событий, health-монитор, дневной отчёт | ✅ |
| 8.5 | Route Intelligence: порт RouteProvider, RouteCostCalculator, ProfitAnalysis, веса 30/30/20/10/10, уведомление ROUTE | ✅ |
| 8.6 | UI Contract Preparation: карточные ViewModel, DashboardViewModel, UI Event Stream, мок-провайдер, золотые снапшоты | ✅ |

## v0.3 — интерфейс

| Этап | Содержимое | Статус |
|---|---|---|
| 9 | Премиальный UI: дизайн-система (docs/design-system.md + токены), библиотека компонентов, shell (сайдбар, статус-бар, тосты, ⌘K), Dashboard с Hero/ScoreRing, qasync, demo-режим | ✅ |
| 9.1 | Формы настроек (токен/Chat ID/проверка, тарифы, веса), реальные почасовые ряды графиков, коалесинг UI-событий, закладки грузов (появится drag-and-drop) | ⬜ |
| 9.5 | Real ATI Integration: AtiAuthProvider, production AtiClient (пагинация, фильтры), дедупликация, RecommendationPipeline, health-job, --demo-ati | ✅ |
| 9.6 | Production Validation: нагрузка 1000 грузов + benchmark, контрактные фикстуры, CargoUpdated, cooldown уведомлений, production-метрики здоровья, security-аудит | ✅ |
| 9.7 | Production Telegram: бот (/status /search /report /settings через Router+CommandBus), категорные HTML-шаблоны, inline-кнопки, BotFather-гайд | ✅ |
| 9.8 | Premium macOS UI Polish (AAA): двойная тема Light/Dark, капсула сайдбара + статус-пилюля + футер-бейджи, живые окончания ScoreRing/Sparkline, каскадные появления и переходы страниц, macOS sheet, Raycast-палитра, 3 уровня тени, скроллбары-невидимки, иллюстрированные empty states | ✅ |
| 9.9 | Dispatcher Workspace: lifecycle статусов грузов, избранное, ignore blacklist, notification history, menu bar, autostart, SQLite cargo history, dispatcher analytics | ✅ |
| 10.0 | Production Route Providers: Yandex Truck Routing, OSRM fallback, geocoding, SQLite route cache, fallback observability, demo/live route smoke | ✅ |
| 10.1 | Real ATI Live Validation + Telegram E2E: Keychain-only ATI/Telegram credentials, token expiry guard, official `byboards`/own-loads endpoints, live pipeline report, Telegram smoke | ◐ |

## v0.4 — распространение (этап 10)

- Упаковка в .app (briefcase/PyInstaller), подпись, нотарификация
- UNUserNotificationCenter вместо osascript-фолбэка
- BuildInfo: дата сборки и git-коммит; окно «О программе»; автообновления

## v1.0 — Windows

- Адаптеры: Credential Manager, WinRT toasts, автозапуск через реестр
