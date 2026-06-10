"""Геометрия гнезда: посадочное отверстие + листовые пружины-детенты в стенке.

Модель «трубки». Круглый хвостовик → цилиндрический бор, hex → шестигранная призма по
стандартному ``socket.hex_size`` (грани держат хвостовик от ПРОВОРОТА). В обоих случаях в стенке
нарезаются лепестки-детенты — они дают ОСЕВУЮ фиксацию (чтобы хвостовик не выпадал из гнезда);
без них hex-биту ничего не держит снизу. Для круглого лепестки идут по окружности, для hex — по
граням призмы. Двумя боковыми пропилами выделяется полоска-балка, за ней — ниша (relief), чтобы
балка отгибалась наружу. Посередине балки — детент (утолщение), выступающий внутрь к хвостовику:
при вставке хвостовик отжимает детенты наружу, и они фиксируют его.

Так как пружины ДОБАВЛЯЮТ материал (детенты внутрь бора), гнездо описывается двумя формами:
  * ``cut``  — что вычесть из корпуса (бор + ниши + боковые пропилы + заходная фаска);
  * ``add``  — что приварить обратно (детенты), или ``None``.
Обе строятся в канонической системе (z в ``[0, depth]``, устье на ``z=depth``) и размещаются
сборкой одним и тем же преобразованием.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import FreeCAD as App
import Part

from ..layout import bore_radius, fit_springs
from ..model import ShankType, Socket, Specs

_Z = App.Vector(0, 0, 1)
_ORIGIN = App.Vector(0, 0, 0)
_LEAD_MAX = 0.8   # максимальная высота заходной фаски, мм


class SocketGeometryError(ValueError):
    """Параметры пружин не дают валидной геометрии (не помещаются по окружности/глубине)."""


def spring_stations(depth: float, springs) -> List[float]:
    """Осевые центры рядов пружин внутри гнезда (с зазорами-заделками у концов)."""
    L = springs.leaf_length
    anchor = max(1.0, springs.slot_width)
    lead = min(_LEAD_MAX, depth * 0.1)
    lo = anchor + L / 2.0
    hi = depth - lead - L / 2.0
    n = max(1, springs.rows)
    if n == 1:
        return [(lo + hi) / 2.0]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _lead_in(r_mouth: float, depth: float) -> Part.Shape:
    """Заходная фаска у устья: расширяющийся конус для удобной вставки хвостовика."""
    ch = min(_LEAD_MAX, depth * 0.1)
    return Part.makeCone(r_mouth, r_mouth + ch, ch, App.Vector(0, 0, depth - ch), _Z)


def _hex_wire(circumradius: float, flat_up: bool, z: float) -> Part.Wire:
    """Контур правильного шестиугольника. ``flat_up`` — гранью вверх, иначе вершиной вверх."""
    offset = 0.0 if flat_up else 30.0
    pts = []
    for i in range(6):
        a = math.radians(offset + 60.0 * i)
        pts.append(App.Vector(circumradius * math.cos(a), circumradius * math.sin(a), z))
    pts.append(pts[0])
    return Part.makePolygon(pts)


def _ring_sector(r_in: float, r_out: float, angle: float, z_lo: float, length: float) -> Part.Shape:
    """Кольцевой сектор [r_in, r_out] × угол × длина по оси, начинающийся с угла 0."""
    outer = Part.makeCylinder(r_out, length, App.Vector(0, 0, z_lo), _Z, angle)
    inner = Part.makeCylinder(r_in, length, App.Vector(0, 0, z_lo), _Z, angle)
    return outer.cut(inner)


def _leaf_cuts(theta: float, z_c: float, r_bore: float, springs) -> List[Part.Shape]:
    """Вырезы вокруг одного лепестка: задняя ниша + два боковых пропила."""
    L = springs.leaf_length
    z_lo = z_c - L / 2.0
    r_leaf_out = r_bore + springs.leaf_thickness
    r_relief_out = r_leaf_out + springs.relief_gap
    leaf_ang = math.degrees(springs.leaf_width / r_bore)
    slot_ang = math.degrees(springs.slot_width / r_bore)

    cuts: List[Part.Shape] = []
    # Задняя ниша за лепестком — место для отгиба наружу.
    relief = _ring_sector(r_leaf_out, r_relief_out, leaf_ang, z_lo, L)
    relief.rotate(_ORIGIN, _Z, theta - leaf_ang / 2.0)
    cuts.append(relief)
    # Два боковых пропила освобождают края лепестка (балка закреплена только сверху/снизу).
    for edge in (-1.0, 1.0):
        slot = _ring_sector(r_bore, r_relief_out, slot_ang, z_lo, L)
        start = theta + edge * (leaf_ang / 2.0) + (0.0 if edge > 0 else -slot_ang)
        slot.rotate(_ORIGIN, _Z, start)
        cuts.append(slot)
    return cuts


def _bump(theta: float, z_c: float, r_bore: float, springs) -> Part.Shape:
    """Детент-утолщение посередине лепестка: тангенциальный валик, выступающий внутрь бора."""
    rb = springs.bump_radius
    # Центр валика по радиусу: чтобы внутренняя кромка вышла на r_bore - bump_protrusion,
    # а внешняя зашла в тело лепестка (бонд при bump_radius >= bump_protrusion/2).
    p = r_bore - springs.bump_protrusion + rb
    half = springs.leaf_width / 2.0
    # Базовую точку задаём прямо в геометрии (-half по оси), чтобы валик был центрирован по
    # ширине лепестка. Через translate нельзя: он меняет placement, который ниже перезаписывается.
    cyl = Part.makeCylinder(rb, springs.leaf_width, App.Vector(0, 0, -half), _Z)
    tangential = App.Vector(-math.sin(math.radians(theta)), math.cos(math.radians(theta)), 0)
    center = App.Vector(p * math.cos(math.radians(theta)), p * math.sin(math.radians(theta)), z_c)
    cyl.Placement = App.Placement(center, App.Rotation(_Z, tangential))
    return cyl


def _fuse(shapes: List[Part.Shape]) -> Part.Shape:
    out = shapes[0]
    for s in shapes[1:]:
        out = out.fuse(s)
    return out


def _hex_flat_angles(flat_up: bool, n: int) -> List[float]:
    """Углы внешних нормалей ``n`` граней hex-призмы (град), равномерно по 6 граням.

    При ``flat_up`` (грань вверх) середины граней на 30°, 90°, …; иначе — на 0°, 60°, ….
    ``n`` детентов раскладываем по граням равномерно (n=3 → через одну, n=6 → на каждой).
    """
    base = 30.0 if flat_up else 0.0
    n = max(1, min(n, 6))
    step = 6 // n if n in (1, 2, 3, 6) else 1  # для делителей 6 — идеально симметрично
    return [base + 60.0 * ((i * step) % 6) for i in range(n)]


def _hex_box(x0: float, x1: float, half_w: float, z_lo: float, length: float, phi: float) -> Part.Shape:
    """Прямоугольный вырез на грани hex в локальной рамке грани, повёрнутой на ``phi``.

    Локальные оси: x — наружу по нормали грани (расстояние от оси), y — вдоль грани (тангента),
    z — вдоль гнезда. Поворот вокруг Z на ``phi`` переводит локальную рамку в каноническую.
    """
    box = Part.makeBox(x1 - x0, 2.0 * half_w, length, App.Vector(x0, -half_w, z_lo))
    box.rotate(_ORIGIN, _Z, phi)
    return box


def _hex_leaf_cuts(phi: float, z_c: float, apothem: float, springs) -> List[Part.Shape]:
    """Вырезы вокруг лепестка на грани hex: задняя ниша + два боковых пропила."""
    L = springs.leaf_length
    z_lo = z_c - L / 2.0
    half_w = springs.leaf_width / 2.0
    x_leaf_out = apothem + springs.leaf_thickness
    x_relief_out = x_leaf_out + springs.relief_gap

    cuts: List[Part.Shape] = []
    # Задняя ниша за лепестком — место для отгиба наружу.
    relief = Part.makeBox(
        springs.relief_gap, springs.leaf_width, L, App.Vector(x_leaf_out, -half_w, z_lo)
    )
    relief.rotate(_ORIGIN, _Z, phi)
    cuts.append(relief)
    # Два боковых пропила освобождают края лепестка (балка закреплена только сверху/снизу).
    for edge in (-1.0, 1.0):
        y0 = edge * half_w if edge > 0 else -half_w - springs.slot_width
        slot = Part.makeBox(
            x_relief_out - apothem, springs.slot_width, L, App.Vector(apothem, y0, z_lo)
        )
        slot.rotate(_ORIGIN, _Z, phi)
        cuts.append(slot)
    return cuts


def _hex_bump(phi: float, z_c: float, apothem: float, springs) -> Part.Shape:
    """Детент-валик посередине лепестка hex: тангенциальный валик, выступающий внутрь от грани."""
    rb = springs.bump_radius
    # Центр валика по нормали: внутренняя кромка выходит на apothem - bump_protrusion,
    # внешняя заходит в тело лепестка (бонд при bump_radius >= bump_protrusion/2).
    x_c = apothem - springs.bump_protrusion + rb
    half = springs.leaf_width / 2.0
    # Ось валика вдоль грани (локальная y); строим в локальной рамке и поворачиваем на phi.
    cyl = Part.makeCylinder(rb, springs.leaf_width, App.Vector(x_c, -half, z_c), App.Vector(0, 1, 0))
    cyl.rotate(_ORIGIN, _Z, phi)
    return cyl


def make_socket(socket: Socket, specs: Specs) -> Tuple[Part.Shape, Optional[Part.Shape]]:
    """Канонические формы гнезда: ``(cut, add)``. ``add`` — детенты пружин или ``None``.

    Пружины подгоняются ПОД ЭТО гнездо (``layout.fit_springs``): count/rows/ширина лепестка зависят
    от бора и глубины. ``None`` от ``fit_springs`` → гладкий бор (пружины выключены или не лезут)."""
    drill = socket.drill
    depth = socket.depth
    springs = fit_springs(drill, depth, specs)  # пер-гнездовая спека или None (гладкий бор)

    # Hex-хвостовик: шестигранное гнездо по стандартному размеру (socket.hex_size), независимо от
    # диаметра сверла. Грани держат от проворота; детенты на гранях — от выпадания (осевая фиксация).
    if drill.shank is ShankType.HEX:
        rc = bore_radius(drill, specs)  # описанный радиус = hex_size/sqrt(3) + hex_clearance
        prism = Part.Face(_hex_wire(rc, specs.socket.hex_flat_up, 0.0)).extrude(App.Vector(0, 0, depth))
        cut_parts: List[Part.Shape] = [prism, _lead_in(rc, depth)]
        if springs is None:
            return _fuse(cut_parts), None
        apothem = rc * math.sqrt(3.0) / 2.0  # расстояние оси до грани, на которой сидит детент
        add_parts: List[Part.Shape] = []
        for phi in _hex_flat_angles(specs.socket.hex_flat_up, springs.count):
            for z_c in spring_stations(depth, springs):
                cut_parts.extend(_hex_leaf_cuts(phi, z_c, apothem, springs))
                add_parts.append(_hex_bump(phi, z_c, apothem, springs))
        return _fuse(cut_parts), _fuse(add_parts)

    # Круглый хвостовик без пружин — простой цилиндр.
    if springs is None:
        r = bore_radius(drill, specs)
        return Part.makeCylinder(r, depth, _ORIGIN, _Z, 360.0).fuse(_lead_in(r, depth)), None

    # Круглый хвостовик с пружинами: круглый бор + листовые детенты.
    r_bore = bore_radius(drill, specs)
    cut_parts: List[Part.Shape] = [
        Part.makeCylinder(r_bore, depth, _ORIGIN, _Z, 360.0),
        _lead_in(r_bore, depth),
    ]
    add_parts: List[Part.Shape] = []
    pitch = 360.0 / springs.count
    for k in range(springs.count):
        theta = k * pitch
        for z_c in spring_stations(depth, springs):
            cut_parts.extend(_leaf_cuts(theta, z_c, r_bore, springs))
            add_parts.append(_bump(theta, z_c, r_bore, springs))

    return _fuse(cut_parts), _fuse(add_parts)
