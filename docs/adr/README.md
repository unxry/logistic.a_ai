# Architecture Decision Records

Каждое существенное архитектурное решение фиксируется отдельным ADR.
Формат — по Майклу Найгарду: Контекст → Решение → Альтернативы → Последствия.

Новый ADR: скопируйте [0000-template.md](0000-template.md), присвойте следующий
номер, добавьте строку в таблицу. ADR не редактируются задним числом: решение
изменилось — пишется новый ADR со ссылкой «заменяет №N».

| № | Решение | Статус |
|---|---|---|
| [0001](0001-clean-architecture.md) | Clean Architecture + Ports & Adapters | Принято |
| [0002](0002-pyside6.md) | PySide6 как GUI-фреймворк | Принято |
| [0003](0003-qasync.md) | qasync: единая петля asyncio + Qt | Принято |
| [0004](0004-event-bus.md) | Собственный типизированный EventBus | Принято |
| [0005](0005-command-bus.md) | CommandBus для всех мутаций | Принято |
| [0006](0006-repository-pattern.md) | Repository Pattern для хранилищ | Принято |
| [0007](0007-sqlite.md) | SQLite через stdlib sqlite3 | Принято |
| [0008](0008-keychain-secrets.md) | Секреты в Keychain через keyring | Принято |
| [0009](0009-vehicle-profile-and-cargo-compatibility.md) | Профиль транспорта и совместимость грузов в домене | Принято |
| [0010](0010-settings-and-secret-storage.md) | Хранение настроек и секретов | Принято |
| [0011](0011-logging-architecture.md) | Архитектура логирования | Принято |
| [0012](0012-telegram-architecture.md) | Архитектура Telegram-подсистемы | Принято |
| [0013](0013-notification-center.md) | Notification Center | Принято |
| [0014](0014-scheduler-runtime.md) | Scheduler Runtime | Принято |
| [0015](0015-cargo-sources-framework.md) | Cargo Sources Framework | Принято |
| [0016](0016-source-configuration.md) | Конфигурация источников, учётные данные, rate limits | Принято |
| [0017](0017-search-engine.md) | Search Engine, стратегия подбора, модель скоринга | Принято |
| [0018](0018-intelligent-matching.md) | Intelligent Matching v1: предпочтения, прибыль, объяснимость | Принято |
| [0019](0019-monitoring-analytics.md) | Monitoring & Analytics | Принято |
| [0020](0020-route-intelligence.md) | Route Intelligence: маршруты и экономика рейса | Принято |
| [0021](0021-ui-contracts.md) | UI-контракты: presentation-слой без Qt | Принято |
| [0022](0022-premium-ui.md) | Премиальный UI: дизайн-система, shell, qasync | Принято |
| [0023](0023-ati-integration.md) | ATI Integration: production-источник грузов | Принято |
| [0024](0024-ati-production-reliability.md) | ATI Production Reliability | Принято |
| [0025](0025-production-telegram.md) | Production Telegram: бот, шаблоны, inline-кнопки | Принято |
| [0026](0026-premium-ui-polish.md) | Премиальный полиш UI: двойная тема, living-motion | Принято |
| [0027](0027-production-route-providers.md) | Production Route Providers: Yandex Truck + OSRM fallback | Принято |
| [0028](0028-ati-live-validation-and-telegram-e2e.md) | ATI Live Validation and Telegram End-to-End | Принято |
| [0029](0029-full-live-ati-commissioning.md) | Full Live ATI Commissioning | Принято |
