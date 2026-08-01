# ADR-0027: Production Route Providers — Yandex Truck + OSRM fallback

- **Статус:** Принято
- **Дата:** 2026-08-01

## Контекст

Stage 8.5 подготовил порт `RouteProvider`, `RouteEstimate` и
`RouteCostCalculator`, но рабочий bootstrap всё ещё использовал
`MockRouteProvider`. Для 12-тонного автомобиля диспетчеру нужен не
автомобильный приблизительный путь, а грузовой маршрут с ограничениями по
весу, габаритам, платным и грунтовым дорогам.

## Решение

1. Основной production provider — `YandexTruckRouteProvider` в
   `app/infrastructure/routes/yandex/`. Он вызывает официальный HTTP routing
   API с `mode=truck`, координатами, габаритами и массой из нейтральной модели
   `RouteVehicleParameters`.
2. Fallback — `OsrmRouteProvider` в `app/infrastructure/routes/osrm/`.
   Он отдаёт расстояние/время, но явно помечается как approximate:
   `supports_truck_restrictions=False`, `traffic_aware=False`,
   `toll_information_available=False`.
3. Последний резерв — `MockRouteProvider` для offline/dev и аварийной оценки.
4. `CompositeRouteProvider` реализует цепочку Yandex → OSRM → stale cache →
   Mock. Matching Engine и Profit Calculator по-прежнему получают только
   `RouteEstimate` через `RouteService`.
5. Геокодинг вынесен в отдельный порт `GeocodingProvider`; реализации:
   `YandexGeocodingProvider`, `CachedGeocodingProvider`,
   `StaticGeocodingProvider`.
6. Persistent cache — порт `RouteCacheRepository` и реализация
   `SqliteRouteCacheRepository`. TTL задаёт `RouteCachePolicy`, а не
   репозиторий: Yandex traffic-aware 45 минут, Yandex static 7 дней, OSRM
   30 дней, geocoding 90 дней.
7. Секрет Yandex хранится только через `SourceCredentialProvider`; в JSON
   сохраняется только `yandex_credentials_reference`.
8. Наблюдаемость идёт через EventBus: `RouteProviderSelected`,
   `RouteCacheHit`, `RouteCacheMiss`, `RouteFallbackUsed`,
   `RouteCalculationFailed`. `RouteMetricsCollector` считает latency,
   cache hit rate, fallback rate, requests/failures by provider.
9. При деградации Yandex одно предупреждение отправляется через существующий
   Notification Center + cooldown. После успешного Yandex-расчёта отправляется
   recovery-сообщение.

## Ограничения

- Yandex сообщает наличие платных участков; фактическая стоимость платной
  дороги может потребовать отдельного тарифного источника. Деньги в LogistAI
  по-прежнему считает `RouteCostCalculator`.
- OSRM public driving profile не учитывает грузовые ограничения, поэтому его
  confidence ниже, а route score слегка уменьшается, но груз не обнуляется.
- Google Routes остаётся необязательным будущим provider: его подключение не
  должно менять порт `RouteProvider`.

## Последствия

(+) Production workflow получает реальные дистанции/время/признак платных
дорог без изменения Search Engine, Notification Center или MVVM.

(+) Cache защищает от повторной оплаты/latency и от cache stampede для
одинаковых concurrent-запросов.

(−) Для полного live smoke нужен ключ Yandex в окружении или Keychain.
