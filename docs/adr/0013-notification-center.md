# ADR-0013: Notification Center

- **Статус:** Принято
- **Дата:** 2026-07-31

## Контекст

С появлением источников (ATI), мониторинга, AI и плагинов уведомления будут
слать все модули. Если каждый знает о Telegram — связность взрывается.
Нужна центральная система, которая останется основой до v1.0.

## Решение

Единственная операция для любого модуля: `await notification_service.send(...)`.
Никто, кроме Notification Center, не знает о каналах, форматтерах, SQLite,
очередях и EventBus.

Компоненты (каждый — одна ответственность):
- **NotificationService** — оркестратор: очередь (`asyncio.Queue` + ленивый
  воркер), координация цепочки, lifecycle-события. Ни if-ов маршрутизации,
  ни форматирования, ни транспорта.
- **NotificationRouter** — все правила выбора каналов: явные `channels`
  уведомления ∩ включённые; WARNING/CRITICAL — все включённые; INFO/SUCCESS —
  основной канал.
- **NotificationDispatcher** — параллельная доставка (`asyncio.gather`),
  изоляция ошибок каналов, сбор DeliveryReport (тайминги, trace_id).
- **ChannelRegistry / FormatterRegistry** — каналы и форматтеры регистрируются
  один раз (bootstrap, позже плагины); форматтер-фолбэк — plain text.
- **История** — общий журнал через порт HistoryRepository (SQLite реализация
  добавлена: WAL, миграции по PRAGMA user_version, `asyncio.to_thread`).
- **События** — lifecycle: NotificationQueued → Sending → Delivered | Failed
  (заменили NotificationDispatched: единый жизненный цикл для Dashboard).

Модель расширена под будущие модули: `NotificationCategory` (system/cargo/
monitor/security/plugin/user/test/error/ai), `NotificationAction` (кнопки —
пока ссылки в Telegram HTML), `payload` (cargo_id и др.), `NotificationContext`
(source/module/user_action/**trace_id**) — сквозная корреляция
Monitor → Notification → канал → журнал. `NotificationBuilder` — fluent-сборка.
`DeliveryReport` расширен: successful/failed_channels, started/finished_at,
duration_ms, attempts, trace_id.

**Telegram стал обычным consumer**: TelegramService реализует порт
NotificationChannel (`send(notification, text)` — текст уже готов) и
регистрируется в реестре наравне с MacOSNotificationChannel (osascript,
runner подменяем в тестах). Собственная очередь Telegram удалена; RateLimiter
остался внутри канала (лимит Telegram — на чат). `channel_id` параметризован —
несколько ботов = несколько экземпляров.

## Альтернативы

- Каждый модуль сам выбирает канал — связность N×M, переписывание при каждом
  новом канале.
- Публикация «сырых» событий и подписка каналов на EventBus — теряется отчёт
  о доставке, порядок и rate-limit координация.

## Последствия

(+) Новый канал/форматтер/категория — один класс + регистрация, ядро и сервис
не меняются; полная трассировка по trace_id; Dashboard получит живой lifecycle.
(−) Порт NotificationChannel изменён (`send(notification, text)`) — осознанно:
форматирование вынесено из каналов (причина: FormatterRegistry). Ретраи
транспорта живут в каналах (Telegram-клиент), NC не ретраит — политика
поверх появится при реальной необходимости. Кластеризация: очередь
инкапсулирована в сервисе — замена на внешний брокер не тронет вызывающих.
