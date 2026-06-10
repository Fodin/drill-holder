"""Опциональный PySide-диалог разовой сборки с правкой конфига.

Пакет разбит по обязанностям (чистые модули без Qt тестируются обычным ``python3``):
  * :mod:`.fields`        — декларации полей (``FieldSpec``) из ``render._CONFIG_SECTIONS``; без Qt;
  * :mod:`.dependencies`  — применимость/валидность/финальная проверка ``build_specs``; без Qt;
  * :mod:`.bulk_input`    — разбор массового ввода диаметров (``parse_diameters``); без Qt;
  * :mod:`.widgets`       — Qt-виджеты полей (``FieldWidget``/``SectionForm``);
  * :mod:`.drill_table`   — таблица свёрел;
  * :mod:`.preview`       — read-only превью сгенерированного конфига;
  * :mod:`.dialog`        — главный диалог ``HolderDialog`` и точка входа ``show_dialog``.

Публичный API — :func:`show_dialog` (его зовёт ``build_holder.py``). Слой знает про
``model``/``config``, но не про FreeCAD (Dependency Rule).

Импорт ``show_dialog`` ленивый: подмодули :mod:`.fields`/:mod:`.dependencies` чистые (без Qt)
и тестируются обычным ``python3``, а импорт подмодуля тянет этот ``__init__`` — поэтому Qt
(через :mod:`.dialog`) подгружается только при реальном вызове диалога.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = ["show_dialog"]


def show_dialog(raw: Dict[str, Any], config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Показать диалог правки конфига (ленивый импорт Qt-слоя). См. :func:`.dialog.show_dialog`."""
    from .dialog import show_dialog as _impl

    return _impl(raw, config_path)
