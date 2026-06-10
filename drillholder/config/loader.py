"""Загрузка «сырого» конфига и слияние с дефолтами.

Конфиг — обычный Python-файл ``holder_config.py`` с dict ``CONFIG`` (правится вручную).
Здесь он импортируется как модуль (из файла) либо исполняется из текста (для GUI-редактора),
после чего недостающие ключи дополняются из :data:`DEFAULTS`. Никакой записи обратно —
источник истины остаётся текстовым (сериализация живёт в :mod:`drillholder.config.render`).

Модуль чистый: FreeCAD не нужен.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict

from .defaults import DEFAULTS
from .errors import ConfigError


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Рекурсивно наложить ``override`` поверх ``base`` (вложенные dict сливаются, не заменяются).

    ``base`` не мутируется — возвращается новый словарь. Списки и скаляры заменяются целиком.
    """
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_raw_config(path: str = "holder_config.py") -> Dict[str, Any]:
    """Импортировать ``holder_config.py`` и вернуть ``CONFIG``, слитый поверх :data:`DEFAULTS`.

    Использует importlib — путь может быть любым (а не только пакетом в PYTHONPATH).
    """
    if not os.path.isfile(path):
        raise ConfigError(f"Файл конфига не найден: {path}")

    spec = importlib.util.spec_from_file_location("holder_config", path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Не удалось загрузить конфиг как модуль: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "CONFIG"):
        raise ConfigError(f"В {path} нет переменной CONFIG (ожидается dict CONFIG = {{...}})")
    user_cfg = module.CONFIG
    if not isinstance(user_cfg, dict):
        raise ConfigError("CONFIG должен быть словарём (dict)")

    return deep_merge(DEFAULTS, user_cfg)


def parse_config_text(text: str) -> Dict[str, Any]:
    """Выполнить текст конфига и вернуть ``CONFIG``, слитый поверх :data:`DEFAULTS`.

    Тот же путь, что и у :func:`load_raw_config` (там importlib), но источник — строка:
    исполняем как Python. Нужна GUI-редактору. Бросает :class:`ConfigError`, если ``CONFIG``
    нет или он не словарь / текст не парсится корректно как словарь.
    """
    namespace: Dict[str, Any] = {}
    exec(compile(text, "<config>", "exec"), namespace)  # noqa: S102 — это пользовательский конфиг
    cfg = namespace.get("CONFIG")
    if not isinstance(cfg, dict):
        raise ConfigError("в тексте нет словаря CONFIG = {...}")
    return deep_merge(DEFAULTS, cfg)
