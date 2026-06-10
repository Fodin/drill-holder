"""Реалистичная 3D-модель спирального сверла для опциональной детали «Drills».

Строится в КАНОНИКЕ гнезда (как :mod:`drillholder.geometry.socket`): дно z=0, устье z=depth, ось +Z.
Хвостовик сидит в гнезде ``z∈[0, depth]`` (круглый цилиндр или hex-призма по ``socket.hex_size``),
выше — режущая часть ``z∈[depth, length−tip_h]`` (спиральная или гладкий цилиндр по
``drill_geometry.style``), на самом верху — конический кончик (угол при вершине ``point_angle_deg``).
Готовая фигура размещается сборкой тем же ``assembly._place_on_surface``, что и гнёзда.

Спираль строится как **loft закрученных поперечных сечений** (``Part.makeLoft(..., ruled=True)``), а не
sweep вдоль винтовой линии: одинаковые по топологии плоские сечения, каждое повёрнуто на малый угол —
самый устойчивый способ в headless Part API (sweep вдоль helix в OCCT часто рвётся). Сечение — диск
радиуса ``d/2`` с ``flutes`` врезанными канавками. Радиус тела сверла — ``d/2`` (НЕ ``bore_radius``:
зазор гнезда к самому́ сверлу не относится).

Любой сбой построения спирали мягко деградирует до гладкого стержня с коническим кончиком и жёлтого
предупреждения — деталь «Drills» собирается из того, что удалось, и НИКОГДА не валит сборку корпуса.

Единственное место (вместе с остальным ``geometry/``), где разрешён ``import Part``.
"""

from __future__ import annotations

import math
from typing import List, Optional

import FreeCAD as App
import Part

from ..model import DrillStyle, ShankType, Socket, Specs
from .socket import _hex_wire  # переиспользуем готовый контур шестигранника (не дублируем формулу)

_Z = App.Vector(0, 0, 1)
_ORIGIN = App.Vector(0, 0, 0)
_TWIST_PER_LAYER_MAX = 20.0   # макс. угол закрутки на слой loft, град (защита от самопересечения)
_LAYERS_CAP = 48              # потолок числа слоёв на одно сверло (производительность)
_SECTION_POINTS = 72          # точек дискретизации контура сечения (полигон вместо дуг — см. ниже)


def _flute_section(r: float, flutes: int, flute_depth: float, z: float) -> Part.Wire:
    """Одно поперечное сечение режущей части на высоте ``z``: диск ``r`` минус ``flutes`` канавок.

    Канавка — «прикус» обода кругом-резцом, смещённым наружу так, что он съедает дугу, но не доходит
    до оси (между канавками остаётся перемычка-сердцевина). Контур дискретизируется в РАВНОМЕРНЫЙ
    полигон из ``_SECTION_POINTS`` точек: loft полигонов даёт прямые линейчатые грани (тело не
    выходит за радиус ``r``), тогда как loft дуг OCCT выгибает сплайном наружу. Полигоны вдобавок
    лофтятся надёжнее, а одинаковое число точек гарантирует идентичную топологию слоёв.
    """
    disk: Part.Shape = Part.Face(Part.Wire(Part.makeCircle(r, App.Vector(0, 0, z), _Z)))
    r_cut = r * 0.65                       # радиус канавочного резца — доля радиуса сверла
    pitch_ang = 360.0 / flutes
    for k in range(flutes):
        a = math.radians(k * pitch_ang)
        cc = r + r_cut - flute_depth       # центр резца по радиусу: режет вглубь на flute_depth
        center = App.Vector(cc * math.cos(a), cc * math.sin(a), z)
        cutter = Part.Face(Part.Wire(Part.makeCircle(r_cut, center, _Z)))
        disk = disk.cut(cutter)            # cut двух граней даёт Compound — грань достаём ниже
    # Булева операция возвращает Compound; берём самую большую по площади грань (остаток диска).
    faces = disk.Faces
    if not faces:
        raise ValueError("сечение канавок пустое")
    contour = max(faces, key=lambda f: f.Area).OuterWire
    # Дискретизируем дуги в равномерный полигон — иначе loft выгибает сплайн за радиус сверла.
    pts = contour.discretize(Number=_SECTION_POINTS)
    return Part.makePolygon(pts + [pts[0]])


def _twisted_flutes(r: float, flute_len: float, flutes: int, flute_depth: float,
                    helix_angle_deg: float, z0: float) -> Part.Shape:
    """Спиральная режущая часть: loft закрученных сечений в ``z∈[z0, z0+flute_len]``.

    Полный угол закрутки берётся из угла винтовой линии: ``pitch = 2π·r/tan(helix)`` — шаг винта,
    ``twist = 360·flute_len/pitch``. Число слоёв подбираем так, чтобы угол на слой не превышал
    ``_TWIST_PER_LAYER_MAX`` (иначе боковые грани самопересекаются), но не больше ``_LAYERS_CAP``.
    """
    helix = math.radians(helix_angle_deg)
    if helix > 1e-6:
        pitch = 2.0 * math.pi * r / math.tan(helix)   # шаг (lead) винтовой линии, мм
        twist_total = 360.0 * flute_len / pitch       # полный угол закрутки на длине flute_len, град
    else:
        twist_total = 0.0
    layers = max(2, math.ceil(abs(twist_total) / _TWIST_PER_LAYER_MAX))
    layers = min(layers, _LAYERS_CAP)

    wires: List[Part.Wire] = []
    for i in range(layers + 1):
        t = i / layers
        section = _flute_section(r, flutes, flute_depth, z0 + t * flute_len)
        section.rotate(_ORIGIN, _Z, twist_total * t)   # закрутка слоя вокруг оси
        wires.append(section)
    # ruled=True — попарно-линейная поверхность между соседними сечениями: устойчивее гладкого
    # сквозного loft для закрученных невыпуклых профилей; при достаточном числе слоёв спираль гладкая.
    return Part.makeLoft(wires, True, True)


def _shank(socket: Socket, specs: Specs, r: float) -> Part.Shape:
    """Хвостовик в зоне гнезда ``z∈[0, depth]``: цилиндр (round) или hex-призма по ``hex_size``."""
    depth = socket.depth
    if socket.drill.shank is ShankType.HEX:
        rc = specs.socket.hex_size / math.sqrt(3.0)   # описанный радиус под ключ (без зазора bore)
        return Part.Face(_hex_wire(rc, specs.socket.hex_flat_up, 0.0)).extrude(App.Vector(0, 0, depth))
    return Part.makeCylinder(r, depth, _ORIGIN, _Z)


def _smooth_body(r: float, z0: float, length_above: float) -> Part.Shape:
    """Гладкий цилиндрический стержень ``z∈[z0, z0+length_above]`` — запасной вариант без спирали."""
    return Part.makeCylinder(r, length_above, App.Vector(0, 0, z0), _Z)


def make_drill_model(socket: Socket, specs: Specs) -> Optional[Part.Shape]:
    """Каноническая модель сверла (дно z=0, кончик наверху) или ``None``, если строить нечего.

    Радиус тела = ``d/2``. Хвостовик в гнезде, спиральная режущая часть выше, конус-кончик на верху.
    Спираль через loft закрученных сечений; при ЛЮБОМ сбое OCCT — мягкий откат на гладкий стержень
    с предупреждением (хвостовик и кончик при этом сохраняются).
    """
    g = specs.drill_geometry
    drill = socket.drill
    r = drill.d / 2.0
    length = drill.length
    if r <= 0.0 or length <= 0.0:
        return None

    # Высота конического кончика из угла при вершине: tip_h = r / tan(point/2).
    tip_h = r / math.tan(math.radians(g.point_angle_deg / 2.0))
    flute_z0 = socket.depth
    flute_top = length - tip_h

    shank = _shank(socket, specs, r)

    # Кончик строим, только если сверло реально выступает выше зоны кончика; иначе — лишь хвостовик.
    if flute_top <= flute_z0:
        # Сверло почти целиком утоплено в гнезде (торчит меньше высоты кончика) — рисуем стерженёк
        # до полной длины со скруглением сверху необязательно; достаточно гладкого цилиндра.
        if length <= flute_z0:
            return shank  # вообще не торчит — только то, что в гнезде
        return shank.fuse(_smooth_body(r, flute_z0, length - flute_z0))

    tip = Part.makeCone(r, 0.0, tip_h, App.Vector(0, 0, flute_top), _Z)
    flute_len = flute_top - flute_z0

    if g.style is DrillStyle.CYLINDER:
        # Гладкий цилиндр без канавок — проще и быстрее, спираль не строим.
        work = _smooth_body(r, flute_z0, flute_len)
    else:
        try:
            flute_depth = r * g.flute_depth_ratio
            work = _twisted_flutes(r, flute_len, g.flutes, flute_depth, g.helix_angle_deg, flute_z0)
            if not work.isValid():
                raise ValueError("loft вернул невалидное тело")
        except Exception as exc:  # noqa: BLE001 — любой сбой OCCT → мягкий откат на гладкий стержень
            App.Console.PrintWarning(
                f"[drill] спираль для d={drill.d} не построилась ({exc}) — откат на гладкий стержень\n"
            )
            work = _smooth_body(r, flute_z0, flute_len)

    return shank.fuse(work).fuse(tip)
