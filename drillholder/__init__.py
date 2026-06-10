"""drillholder — параметрический генератор подставки для хранения свёрел (FreeCAD).

Пакет разделён по принципу Clean Architecture (Dependency Rule):

* Ядро (без FreeCAD, тестируется обычным Python):
    - :mod:`drillholder.model`  — Value Objects и перечисления.
    - :mod:`drillholder.config` — загрузка/слияние/валидация конфига.
    - :mod:`drillholder.layout` — расчёт раскладки гнёзд.
* Адаптеры к FreeCAD (Humble Object на границе):
    - :mod:`drillholder.geometry` — построение твёрдого тела.
    - :mod:`drillholder.export`   — запись FCStd/STL/STEP.
    - :mod:`drillholder.gui`      — опциональный PySide2-диалог.

Зависимости направлены внутрь: адаптеры знают про ядро, ядро не знает про FreeCAD.
"""

__version__ = "0.1.0"
