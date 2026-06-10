"""Геометрический слой — адаптер к FreeCAD (Humble Object на границе).

Единственное место, где импортируются ``FreeCAD``/``Part``/``Draft``/``MeshPart``. Принимает
:class:`drillholder.model.ResolvedPlan` из чистого ядра и превращает его в твёрдое тело.
"""

from .assembly import build_model  # noqa: F401
