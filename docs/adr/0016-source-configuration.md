# ADR-0016: Конфигурация источников, учётные данные и rate limits

- **Статус:** Принято
- **Дата:** 2026-07-31

## Контекст

Двигатель источников готов (ADR-0015), но источник «зашитый» в код бесполезен
пользователю: ATI/Ozon/WB должны добавляться через настройки. Плюс реальные
API требуют секретов и лимитов частоты.

## Решение

1. **SourceConfiguration** (домен): source_id, enabled, name,
   `credentials_reference` (ссылка — НЕ секрет), polling_interval_seconds,
   max_results, filters, created/updated_at. Хранение —
   `JsonSourceConfigurationRepository` (sources.json, атомарная запись,
   толерантный парсинг; SQLite позже за тем же портом
   `SourceConfigurationRepository`: get_all/get/save/delete/enable/disable).
2. **Секреты** — порт `SourceCredentialProvider.get(reference, field)`
   (поля: login/password/api_key/token); реализация
   `KeychainSourceCredentialProvider` поверх порта SecretStore
   (ключ `source:{reference}:{field}`) — ядро не знает Keychain, инфраструктура
   зависит только от core.
3. **Эффективная конфигурация**: пользовательский конфиг имеет приоритет над
   заводским spec (enabled, интервал опроса); скелеты реальных источников
   поставляются с `enabled=False` — оживают только конфигурацией.
   `SourceContext.configuration` передаёт max_results/filters/credentials_reference.
4. **Rate limits**: `SourceRateLimitPolicy` (requests_per_minute, burst_limit)
   в spec; token-bucket `SourceRateLimiter` в runtime перед каждой попыткой,
   лог превышений, уведомление при ожидании >10 с; `SourceRateLimitError.retry_after`
   уважается при ретраях.
5. **Здоровье расширено**: last_error_at, consecutive_failures,
   last_received_count — Dashboard покажет «ATI 🟢 / получено / ошибок».
6. **Каталог**: `SourceRegistry.list_available_sources() → SourceDescriptor`
   (id, name, version, capabilities, requires_credentials, supported_regions).
7. **ATI-скелет** (`infrastructure/sources/ati/`): source.py (порт готов,
   spec: 5 capabilities, 5 мин, 30 req/min, `enabled=False`), client.py
   (транспорт — единственное, что изменится в Stage 5.2), mapper.py (поля ATI →
   RawCargo с пометкой единиц: тонны/метры/м³), errors.py (статусы → SourceError).

## Последствия

(+) Добавление Ozon = каталог `infrastructure/sources/ozon/` + регистрация —
ничего больше (проверено аудитом); пользовательское включение — конфигурацией.
(−) Реальный ATI API (Stage 5.2) потребует учётки владельца — секреты кладутся
в Keychain (`source:<ref>:api_key`), в репозиторий и чат не попадают.
