# ADR-0019: Monitoring & Analytics

- **Статус:** Принято
- **Дата:** 2026-07-31

## Контекст

Платформа принимает решения (источники, подбор, задачи) — нужна
наблюдаемость: сколько найдено, что эффективно, почему отказы, сколько
потенциально заработано.

## Решение

1. **Модели аналитики** (core): SourceAnalytics, MatchingAnalytics,
   DriverAnalytics + чистая функция `summarize_decisions` в ядре — её
   переиспользуют и сервис качества, и SQLite-хранилище (без нарушения
   контракта infrastructure → core).
2. **MatchingDecision расширен** (vehicle_profile_id, profit, explanation,
   route) и хранится в SQLite (миграция схемы v2 через PRAGMA user_version);
   порт `MatchingRepository`: save_decision / get_history / get_statistics /
   driver_statistics.
3. **Сбор из существующих событий**: AnalyticsCollector подписывается на
   CargoReceived / SourceCompleted / SourceFailed / CargoMatched /
   CargoRejected / JobFailed (счётчики в памяти); DecisionPersister —
   MatchingDecisionCreated → fire-and-forget сохранение (ссылки на задачи
   удерживаются — RUF006).
4. **SourceHealthMonitor**: FAILED дольше порога (15 мин от last_success) →
   одно уведомление «⚠️ … недоступен N минут»; восстановление сбрасывает
   сторожок.
5. **MatchingQualityService** — «почему выбран/отвергнут» в цифрах: топ
   причин отказов, лучшие маршруты, средние балл и прибыль.
6. **DailyAnalyticsReportJob** — обычный Job для Scheduler: «Отчёт LogistAI»
   (найдено / подходящих / лучший маршрут / средняя прибыль / ошибки
   источников) через Notification Center.

## Последствия

(+) Решения копятся в SQLite с trace_id — готовая база для обучения (Stage 7)
и Dashboard (Stage 9); отчёт и монитор — обычные компоненты поверх портов.
(−) Счётчики коллектора живут в памяти процесса (персистентная агрегация по
периодам — вместе с Dashboard); DriverAnalytics считает по всем решениям без
периодов (периодизация — Stage 9).
