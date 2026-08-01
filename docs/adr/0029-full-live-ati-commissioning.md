# ADR-0029: Full Live ATI Commissioning

- **Статус:** Принято
- **Дата:** 2026-08-01

## Контекст

Stage 10.1 подтвердил безопасную авторизацию ATI и рабочий Telegram, но не
подтвердил получение реального груза: официальные ATI endpoints вернули
`Received: 0`. Для production нельзя считать HTTP 200 доказательством
рыночной выдачи.

## Решение

1. Ввести commissioning-скрипты:
   - `scripts/ati_access_diagnostics.py`;
   - `scripts/ati_live_smoke.py --no-filters|--minimal-filters|--vehicle-filters`;
   - `scripts/yandex_routes_smoke.py`;
   - `scripts/telegram_live_smoke.py`;
   - `scripts/live_end_to_end.py`.
2. Сохранять `LivePipelineReport` в JSON-лог и SQLite-таблицу
   `live_pipeline_reports`.
3. Разделять состояния:
   - ATI authenticated;
   - personal board access;
   - data available;
   - matched cargo available.
4. Запрещать формулировку “LogistAI получает реальные грузы ATI”, пока
   `Real cargo received == 0`.
5. Secret scanning становится частью pre-commit и CI через `detect-secrets`.

## Подтверждённое ограничение ATI

Официальная документация ATI для перевозчика говорит, что поиск грузов через
API поддержан только на Персональных площадках. Общая площадка ATI.SU не
является источником общей рыночной выдачи через `byboards`.

## Последствия

(+) Live commissioning теперь доказывает именно доступ к данным, а не только
аутентификацию.
(+) Если доступ пустой, отчёт содержит подтверждённую причину и следующий
официальный шаг.
(−) Для завершения полного E2E с `Real cargo received > 0` нужен аккаунт/token
с доступом к непустой Персональной площадке, подходящий ATI тариф/API-scope или
иной официальный механизм ATI.
