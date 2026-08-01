# Настройка окружения разработки

## Требования

- macOS 13+ (целевая платформа; разработка возможна и на Linux — тесты идут offscreen)
- [uv](https://docs.astral.sh/uv/) — менеджер пакетов и Python-версий
- Git

## Установка

```bash
git clone <репозиторий> && cd LogistAI
uv sync                                            # Python 3.13 + зависимости (+dev)
mv pre-commit-config.yaml .pre-commit-config.yaml  # однократно (см. примечание в файле)
uv run pre-commit install                          # git-хуки — обязательно
```

## Ежедневные команды

| Команда | Назначение |
|---|---|
| `uv run python main.py` | запуск приложения |
| `uv run pytest` | все тесты |
| `uv run pytest tests/unit -q` | только unit |
| `uv run ruff format .` | форматирование |
| `uv run ruff check --fix .` | линтер с автофиксом |
| `uv run mypy` | проверка типов (strict) |
| `uv run lint-imports` | архитектурные контракты |
| `uv run pre-commit run --all-files` | все хуки разом |

## Тесты и GUI

UI-тесты выполняются offscreen (`QT_QPA_PLATFORM=offscreen` ставится в
`tests/conftest.py`) — дисплей не нужен, работает в CI. На Linux для Qt нужны
системные библиотеки: `libgl1 libegl1 libxkbcommon0` (см. `.github/workflows/ci.yml`).

## Переменные окружения

| Переменная | Значения | Назначение |
|---|---|---|
| `LOGISTAI_MODE` | `debug` (по умолчанию) / `release` | режим сборки в BuildInfo |
| `QT_QPA_PLATFORM` | `offscreen` | headless-запуск Qt |

## CI

GitHub Actions (`.github/workflows/ci.yml`) на каждый push и PR:
Linux — формат, линтер, mypy, import-linter, pytest; macOS — pytest.
Красный CI не мержится.
