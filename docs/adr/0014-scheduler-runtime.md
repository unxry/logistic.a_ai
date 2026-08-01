# ADR-0014: Scheduler Runtime

- **Статус:** Принято
- **Дата:** 2026-07-31

## Контекст

Вся headless-инфраструктура готова (ядро, настройки, Telegram, Notification
Center, журнал) — не хватает двигателя, который будет запускать ATI Monitor,
Cargo Search, плагины, чистку, health-check, аналитику и бэкапы. UI осознанно
отложен: интерфейс строится один раз поверх готовых движков (roadmap headless-first).

## Решение

1. **Job = данные + одна корутина.** Порт `Job` сокращён до `spec: JobSpec` и
   `run(context)`. Всё поведение runtime описано данными `JobSpec` (schedule,
   timeout, retry, max_parallel_runs) — поэтому исполнитель заменяем
   (asyncio → APScheduler → кластер) без изменения ни одной задачи, и наоборот.
2. **Политики запуска — стратегии**: `RunOnce`, `Interval` (джиттер),
   `Cron`/`Adaptive` — заготовки (NotImplementedError до первого сценария;
   Cron — на croniter, Adaptive — вместе с мониторингом).
3. **JobContext** — все зависимости задачи одним объектом: logger,
   notifications (порт `NotificationSender` — новый микро-порт ядра),
   history (порт), settings-провайдер, trace_factory, clock и `trace_id`
   текущего запуска. Задачи не импортируют сервисы вообще.
4. **SchedulerRuntime** — единственный исполнитель: супервизор-задача на
   каждую job (расписание → ожидание → запуск), `JobRegistry` без if-ов,
   graceful cancel. Watchdog встроен: таймаут через `asyncio.wait_for`
   отменяет зависшую задачу; упавший супервизор не роняет runtime.
5. **Ретраи** — отдельная `JobRetryPolicy` (по умолчанию без повторов;
   транспортная политика Telegram не переиспользуется — у задач своя семантика).
6. **Параллелизм** — `max_parallel_runs` (по умолчанию 1): повторный запуск
   пропускается с событием `JobSkipped`.
7. **Наблюдаемость**: метрики на задачу (runs, failures, success_rate,
   average_duration, last/next_run — frozen-снапшоты); каждый запуск — запись
   в журнал (SYSTEM_EVENT, свой **trace_id**) и события JobStarted/Completed/
   Failed/Skipped + SchedulerStarted/Stopped; при ошибке — уведомление через
   Notification Center (Scheduler не знает о Telegram).
8. **Управление — команды**: StartScheduler, StopScheduler, PauseJob,
   ResumeJob, RunJobNow (возвращает JobResult; ручной запуск игнорирует паузу).
9. Встроенная задача v0.1: `HistoryCleanupJob` (ежедневная чистка журнала по
   retention из настроек) — образец задачи на чистом JobContext.

## Альтернативы

- APScheduler — тяжёлая зависимость, своя модель исполнения; наш runtime
  ~300 строк под полным контролем, а контракт Job позволяет мигрировать позже.
- Один tick-цикл на все задачи — проще, но паузы/параллелизм/таймауты каждого
  job загрязняют общий цикл; супервизор-на-задачу изолирует отказы.

## Последствия

(+) ATI Monitor / Cargo Search / Backup / Plugin Job = один класс с JobSpec +
регистрация; исполнитель заменяем без изменения задач. (−) Пауза, случившаяся
во время ожидания, не отменяет уже запланированный ближайший запуск после
resume (осознанно, задокументировано); debounce уведомлений о повторных
ошибках задачи появится с мониторингом.
