"""Общие настройки тестов."""

import os

# В headless-окружениях (CI, контейнеры) Qt работает через offscreen-плагин.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
