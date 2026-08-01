# ADR-0021: UI Contract Preparation — presentation-слой без Qt

- **Статус:** Принято
- **Дата:** 2026-07-31

## Контекст

Интерфейс (Stage 9) будет строить отдельный агент. Ему нужны стабильные
контракты данных и «красивые» примеры, но давать ему доменную логику
(подбор, маршруты, SQLite) нельзя: UI должен остаться тонким. Значит,
границу View ↔ платформа надо зафиксировать заранее — типами, событиями
и снапшотами.

## Решение

1. **Карточные ViewModel** (`app/ui/viewmodels/cards.py`) — неизменяемые
   dataclass'ы с готовыми к отрисовке строками («120 000 ₽», «5 мин назад»)
   и числами для индикаторов (score, проценты): CargoCardViewModel,
   SourceStatusViewModel, AnalyticsViewModel, VehicleViewModel,
   EventRowViewModel, StatusBadge (светофорный BadgeTone), ActionViewModel,
   агрегат DashboardSnapshot. Фабрики ``from_*`` переводят модели ядра в
   презентационную форму; форматирование — чистые функции ``formatting.py``.
2. **DashboardViewModel** — презентер: слушает доменные события
   (TelegramStatusChanged, SourceHealthChanged, CargoReceived, AppStarted),
   держит состояние, ``refresh()`` тянет аналитику и журнал через порт,
   ``update_recommendations()`` принимает результаты подбора. Свойства по
   ТЗ: application_status, telegram_status, sources_status, active_vehicle,
   best_matches, analytics_summary, recent_events.
3. **UI Event Stream** (`events.py`): DashboardUpdated (полный снапшот),
   CargoRecommendationChanged, SourceStatusChanged. Будущие виджеты
   подписываются на ТРИ события вместо двух десятков доменных.
4. **Порты presentation-слоя** (`ports.py`): DashboardDataProvider (данные)
   и EventStream (шина; EventBus совместим структурно). Живой адаптер —
   ``DashboardDataService`` (`app/services/presentation`), который
   удовлетворяет порт СТРУКТУРНО, не импортируя ui (services не знают ui);
   соответствие проверяет mypy в composition root.
5. **MockDashboardDataProvider** (`mock_data.py`) — детерминированные
   красивые данные (фиксированные MOCK_NOW и id): три источника во всех
   состояниях, аналитика насыщенного дня, журнал, MAN TGL и три готовые
   карточки рекомендаций (эталон ТЗ 85 000 ₽ первой). UI строится и
   верстается вообще без домена.
6. **Снапшот-тесты**: ``snapshot_dict`` (dataclass → JSON-форма) +
   золотые файлы ``tests/snapshots/*.json`` — зафиксированный контракт;
   изменение формы ломает тест, обновление — осознанно через
   ``LOGISTAI_UPDATE_SNAPSHOTS=1``.
7. **Седьмой контракт import-linter** (include_external_packages):
   ``app.ui.viewmodels`` не импортирует PySide6, services, infrastructure,
   buses, plugins, container, bootstrap — правило «ViewModel не знает Qt,
   только ядро и порты» принудительно машинно. Плюс subprocess-тест:
   импорт пакета не тянет PySide6.

## Альтернативы

- *Отдать UI-агенту сервисы напрямую* — размывает MVVM, UI пришлось бы
  знать асинхронные порты, SQLite и домен; отказ.
- *Qt-сигналы уже сейчас* — привязали бы контракты к PySide6 до появления
  UI и сломали бы headless-тесты; UI Event Stream на EventBus переводится
  в сигналы адаптером в Stage 9.
- *JSON-схемы вместо dataclass'ов* — теряется типизация mypy strict.

## Последствия

(+) UI-агент получает: типизированные карточки, три события, мок с красивыми
данными и золотые снапшоты — экран рисуется без единого импорта домена.
(−) DashboardViewModel обновляет аналитику только в ``refresh()``
(периодичность повесит qasync в Stage 9); UI-события публикуются на каждое
изменение без коалесинга (при живом потоке добавим debounce в Stage 9).
