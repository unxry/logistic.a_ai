# ADR-0023: ATI Integration — production-источник грузов

- **Статус:** Принято
- **Дата:** 2026-07-31

## Контекст

Скелет ATI (Stage 5.1) держал контракт, но не ходил в сеть. Нужен
production-источник: авторизация, пагинация, фильтры, устойчивость к сбоям,
дедупликация и доведение груза до рекомендации — БЕЗ изменения ядра и
только через существующие точки расширения (SourceRuntime, Scheduler,
Notification Center, AnalyticsCollector).

## Решение

1. **Весь ATI — в `infrastructure/sources/ati/`**: auth.py, client.py,
   mapper.py, source.py, errors.py, demo.py. Ядро, порты и события не
   менялись вообще.
2. **AtiAuthProvider**: два режима на одну Keychain-ссылку —
   статический ``api_key``/``token`` (личный ключ кабинета ATI) или сессия
   ``login``+``password`` (POST /auth/v1.0/token, кеш с зазором 60 с,
   обновление по истечении). 401 → инвалидация + ОДИН повтор с новым
   токеном; 403 → SourceAuthenticationError; 429 → SourceRateLimitError
   с Retry-After. Секреты не логируются и не попадают в тексты ошибок.
3. **AtiClient**: httpx.AsyncClient (таймауты 5/10/10/5, как в ADR-0012),
   пагинация POST /v1.0/loads/search (per_page 50, страховка 20 страниц,
   срез до max_results), get_load, verify, graceful ``aclose()`` из
   composition root. Разделение повторов: клиент повторяет ТОЛЬКО
   транспортные сбои (сеть/5xx, 3 попытки с backoff); политику опроса
   (ретраи, паузы 429, rate limit token-bucket) ведёт SourceRuntime по
   SourceSpec — слои не дублируются.
4. **Mapper**: вложенный боевой формат (cargo/loading/unloading/payment) и
   плоский legacy; вес числом (тонны ATI), объектом {quantity, type} или
   строкой («5 т», «5000 кг», «5.5 тонн»); комбинированные габариты
   «6.2x2.45x2.5» (x/х/×/*); даты загрузки/доставки — в атрибуты; полный
   payload сохраняется в ``RawCargo.raw`` (raw_metadata — ничего не
   теряется). Конверсию единиц делает существующий CargoNormalizer.
5. **Конфигурация** — существующая SourceConfiguration: enabled,
   polling_interval_seconds (ATI-POLL, 300 с), max_results,
   credentials_reference и filters (regions, cargo_types, min_weight,
   max_weight, min_price) — клиент переводит их в тело запроса ATI.
6. **Дедупликация** (`services/sources/dedup.py`): fingerprint =
   sha256(источник|id|откуда|куда|вес|цена) — изменившаяся цена считается
   новым предложением; CargoDeduplicator — LRU на 5000 отпечатков.
7. **RecommendationPipeline** (`services/search/pipeline.py`) — связующее
   звено конвейера: CargoReceived → дедуп → CargoRepository → Search →
   Intelligent Matching (rank один раз + новый ``select_from_ranked`` без
   повторной оценки) → notify_best (категория ROUTE) → колбэк
   ``on_ranked`` в дашборд (инжектируется в bootstrap — services не знают ui).
8. **Scheduler при старте приложения**: run_app диспатчит StartScheduler —
   ATI-POLL (интервал из конфигурации) и новый SourceHealthCheckJob
   (минутный прогон SourceHealthMonitor: «⚠️ источник недоступен N минут»,
   однократно до восстановления) работают без участия пользователя.
   Shutdown: StopScheduler → wait_idle пайплайна → aclose клиента.
9. **Analytics**: AnalyticsCollector расширен дубликатами
   (duplicate_count в SourceAnalytics), средней ценой и топ-направлениями
   per source (из CargoReceived) — счётчики в памяти процесса.
10. **--demo-ati**: боевой конвейер на httpx.MockTransport — реальные
    auth/пагинация/mapper/normalizer/дедуп/подбор/уведомление без внешней
    сети; демо-учётки фиктивны, пользовательский sources.json не трогается.

## Альтернативы

- *Ретраи и rate limit в клиенте целиком* — дублировало бы политики
  SourceRuntime и вело к шторму повторов; клиент повторяет только транспорт.
- *Дедупликация в SourceRuntime* — раздула бы runtime и потеряла связь с
  сохранением; пайплайн владеет «сохранить новые» атомарно.
- *Дедупликация в SQLite* — прежде времени; LRU процесса достаточно для
  цикла опроса, персистентность — вместе с SQLite-хранилищем грузов.

## Последствия

(+) Пользователь подключает ATI настройками (Keychain + sources.json), код
не меняется; конвейер до уведомления и дашборда работает автоматически;
демо-режим доказывает весь путь без сети. Контракты import-linter 7/7 —
ядро не тронуто.
(−) Точные имена полей боевого API ATI могут отличаться — эндпоинты и
маппинг собраны в константах client.py/mapper.py и правятся точечно;
уведомление об ошибке источника шлётся на каждый неудачный опрос
(троттлинг — Stage 9.6); счётчики аналитики живут в памяти процесса.
