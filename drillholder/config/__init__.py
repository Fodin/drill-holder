"""Загрузка, слияние с дефолтами, валидация и сериализация пользовательского конфига.

Пакет разбит по осям изменения (одна причина для правок на модуль):
  * :mod:`.defaults`  — :data:`DEFAULTS` (зеркало holder_config.py и дефолтов dataclass'ов);
  * :mod:`.loader`    — чтение «сырого» конфига из файла/текста и слияние с дефолтами;
  * :mod:`.validate`  — проверка значений и сборка типизированных Value Objects (``Specs``);
  * :mod:`.render`    — обратная сериализация в самодокументированный ``holder_config.py``;
  * :mod:`.errors`    — :class:`ConfigError`.

Публичный API экспортируется отсюда — внешний код импортирует из ``drillholder.config``,
не зная о внутренней раскладке. Слой чистый: FreeCAD не нужен, всё тестируется обычным Python.
"""

from __future__ import annotations

from .calibration import (
    DEFAULT_CLEARANCES,
    DEFAULT_TEST_DRILLS,
    calibration_config,
)
from .defaults import DEFAULTS
from .errors import ConfigError
from .loader import deep_merge, load_raw_config, parse_config_text
from .render import render_config
from .validate import build_specs, load_config

__all__ = [
    "ConfigError",
    "DEFAULTS",
    "deep_merge",
    "load_raw_config",
    "parse_config_text",
    "build_specs",
    "load_config",
    "render_config",
    "calibration_config",
    "DEFAULT_TEST_DRILLS",
    "DEFAULT_CLEARANCES",
]
