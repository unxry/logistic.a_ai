# ADR-0028: ATI Live Validation and Telegram End-to-End

- **Статус:** Принято
- **Дата:** 2026-08-01

## Контекст

Stage 10.1 переводит рабочий ATI-конвейер из demo/mock режима в live-режим:
официальный ATI API → нормализация → SQLite → Search/Matching → Notification
Center → Telegram/UI. Секреты должны храниться только локально в системном
хранилище, без JSON, логов, скриншотов и Git.

## Решение

- ATI credentials хранятся через существующий `SourceCredentialProvider` поверх
  `KeychainSecretStore`:
  - `source:ati_main:client_id`;
  - `source:ati_main:access_token`;
  - `source:ati_main:token_expires_at`.
- Telegram хранит и Bot Token, и Chat ID в Keychain:
  - `telegram_bot_token`;
  - `telegram_chat_id`.
- Live ATI source использует только официальные endpoints:
  - `GET /v1.0/loads/search/byboards` — грузы на доступных персональных
    площадках, carrier use-case;
  - `GET /v1.0/loads` — отдельный режим для собственных опубликованных грузов.
- Demo clients/sources остаются только для `--demo`, `--demo-ati` и тестов.
- Перед polling проверяется `AtiTokenState`; истёкший token не используется и
  HTTP-запросы к ATI не выполняются.
- `scripts/ati_live_smoke.py` запускает production container без demo fixtures,
  пишет `AtiPipelineReport` и отправляет одно Telegram test notification.

## Ограничения ATI

Официальная документация ATI разделяет общую площадку и персональные площадки.
Через `byboards` перевозчик получает грузы только с доступных персональных
площадок. Если аккаунт не состоит в такой площадке или там нет грузов, API
может успешно аутентифицироваться и вернуть пустой список. В этом случае
LogistAI не подменяет результат fixtures: live-smoke завершается с ненулевым
кодом, потому что реальных грузов не получено.

## Последствия

(+) Live-режим не смешивает реальные и demo данные.
(+) Секреты не попадают в JSON/SQLite/Git и не печатаются в smoke output.
(+) Истёкший ATI token не вызывает бесконечных 401-запросов.
(−) Для marketplace-like потока нужны доступ к персональной площадке, webhook
или отдельный платный официальный ATI endpoint; browser scraping запрещён.
