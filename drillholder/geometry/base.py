"""Корпус подставки и геометрия её рабочей поверхности.

Для прямоугольной раскладки верхняя грань горизонтальна; для ``angled`` корпус — клин с
наклонной верхней гранью. :class:`Surface` инкапсулирует ориентацию этой грани (нормаль,
поворот, базис) — её используют и сверление гнёзд, и гравировка подписей, чтобы не дублировать
тригонометрию наклона.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import FreeCAD as App
import Part

from ..layout import socket_extents
from ..model import LayoutMode, ResolvedPlan, Socket, Specs


class Surface:
    """Рабочая (верхняя) грань корпуса: точка входа гнезда и его ориентация.

    Локальный базис: ``u`` — вдоль X, ``v`` — касательная к грани в направлении Y,
    ``normal`` — внешняя нормаль. ``rotation`` переводит мировой +Z в ``normal``
    (для прямой грани это тождество).
    """

    def __init__(self, angle_deg: float, h_front: float, y_front: float) -> None:
        self._angle = math.radians(angle_deg)
        self._h_front = h_front
        self._y_front = y_front
        self.rotation = App.Rotation(App.Vector(1, 0, 0), angle_deg)
        self.normal = self.rotation.multVec(App.Vector(0, 0, 1))
        self.u = App.Vector(1, 0, 0)
        self.v = self.rotation.multVec(App.Vector(0, 1, 0))

    def point(self, x: float, y: float) -> App.Vector:
        """Точка на поверхности над плановой позицией ``(x, y)``."""
        z = self._h_front + (y - self._y_front) * math.tan(self._angle)
        return App.Vector(x, y, z)


def _extent(sockets: List[Socket], specs: Specs) -> Tuple[float, float, float, float]:
    """Габариты раскладки по центрам гнёзд, расширенные на габарит «гнездо + подпись».

    Берём те же полугабариты, что и упаковка (``socket_extents``), чтобы корпус заведомо вмещал
    вынесенные подписи, а не только сами гнёзда.
    """
    ext = [(s, socket_extents(s.drill, specs)) for s in sockets]
    xmin = min(s.x - e["left"] for s, e in ext)
    xmax = max(s.x + e["right"] for s, e in ext)
    ymin = min(s.y - e["front"] for s, e in ext)
    ymax = max(s.y + e["back"] for s, e in ext)
    return xmin, xmax, ymin, ymax


def make_base(plan: ResolvedPlan) -> Tuple[Part.Shape, Surface]:
    """Построить корпус и вернуть ``(shape, surface)``.

    Высота подбирается так, чтобы под самым глубоким гнездом оставалось дно ``floor``.
    """
    sockets = plan.sockets
    specs = plan.specs
    margin = specs.layout.edge_margin
    floor = specs.base.floor
    max_depth = max(s.depth for s in sockets)

    xmin, xmax, ymin, ymax = _extent(sockets, specs)
    x0 = xmin - margin
    y0 = ymin - margin
    width = (xmax - xmin) + 2 * margin
    depth_y = (ymax - ymin) + 2 * margin

    if plan.resolved_mode is LayoutMode.ANGLED:
        # Наклонённые гнёзда уходят осью назад-вниз на depth*sin(angle); удлиняем заднюю
        # (высокую) часть клина на это смещение + радиус, иначе гнездо протыкает заднюю грань.
        max_r = max(s.outer_radius for s in sockets)
        back_pad = max_depth * math.sin(math.radians(specs.layout.angle_deg)) + max_r
        return _make_angled(specs, x0, y0, width, depth_y + back_pad, floor, max_depth)
    return _make_flat(specs, x0, y0, width, depth_y, floor, max_depth)


def _make_flat(specs, x0, y0, width, depth_y, floor, max_depth):
    height = max(specs.base.min_height, floor + max_depth)
    box = Part.makeBox(width, depth_y, height, App.Vector(x0, y0, 0))
    # Прямая грань: нормаль вверх, точка входа на высоте корпуса.
    surface = Surface(angle_deg=0.0, h_front=height, y_front=y0)
    return box, surface


def _make_angled(specs, x0, y0, width, depth_y, floor, max_depth):
    angle = specs.layout.angle_deg
    # Вертикального запаса спереди хватает на полную глубину гнезда + дно.
    h_front = floor + max_depth
    h_back = h_front + depth_y * math.tan(math.radians(angle))
    y1 = y0 + depth_y

    # Профиль-трапеция в плоскости YZ (при x = x0), затем выдавливаем вдоль X на всю ширину.
    pts = [
        App.Vector(x0, y0, 0.0),       # перёд-низ
        App.Vector(x0, y1, 0.0),       # зад-низ
        App.Vector(x0, y1, h_back),    # зад-верх
        App.Vector(x0, y0, h_front),   # перёд-верх (наклонная грань P3->P2)
        App.Vector(x0, y0, 0.0),       # замыкание
    ]
    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    wedge = face.extrude(App.Vector(width, 0, 0))
    surface = Surface(angle_deg=angle, h_front=h_front, y_front=y0)
    return wedge, surface
