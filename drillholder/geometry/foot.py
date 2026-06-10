"""Устойчивое основание (foot): расширенная опорная плита снизу корпуса.

MANUAL — плита выносится за габарит корпуса на заданный ``margin``. AUTO — вынос считается по
центру тяжести (корпус + свёрла, сталь тяжелее пластика и выше → доминирует в опрокидывании) и
углу опрокидывания: полупролёт опоры ≥ высота_ЦТ · tan(tip_angle). Плита вфьюзивается в корпус.
"""

from __future__ import annotations

import math

import FreeCAD as App
import Part

from ..model import FootMode, ResolvedPlan

# Плотность сверла относительно пластика корпуса (сталь ~7.9 vs PLA ~1.24 г/см³).
_DRILL_DENSITY = 6.0


def _shape_com(shape: Part.Shape) -> App.Vector:
    """Центр масс формы; у Compound нет .CenterOfMass — считаем по солидам."""
    try:
        return shape.CenterOfMass
    except Exception:  # noqa: BLE001 — Compound и т.п.
        solids = shape.Solids
        if solids:
            tot = 0.0
            acc = App.Vector()
            for s in solids:
                v = s.Volume
                acc = acc + s.CenterOfMass * v
                tot += v
            return acc * (1.0 / tot)
        return shape.BoundBox.Center


def _center_of_gravity(body: Part.Shape, plan: ResolvedPlan, top_z: float):
    """Приблизительный ЦТ системы «корпус + свёрла» (вектор) и суммарная «масса»."""
    m_body = body.Volume
    cg = _shape_com(body) * m_body
    total = m_body
    for s in plan.sockets:
        protr = max(0.0, s.drill.length - s.depth)
        vol = math.pi * (s.drill.d / 2.0) ** 2 * s.drill.length      # объём сверла (прибл.)
        m = _DRILL_DENSITY * vol
        z_c = top_z + (protr - s.depth) / 2.0                        # центр сверла по оси
        cg = cg + App.Vector(s.x, s.y, z_c) * m
        total += m
    return cg * (1.0 / total), total


def make_foot(body: Part.Shape, plan: ResolvedPlan, top_z: float, max_protrusion: float) -> Part.Shape:
    """Построить плиту основания (для последующего fuse в корпус)."""
    foot = plan.specs.foot
    bb = body.BoundBox
    xmin, xmax, ymin, ymax = bb.XMin, bb.XMax, bb.YMin, bb.YMax

    if foot.mode is FootMode.MANUAL:
        m = foot.margin
        left, right, front, back = xmin - m, xmax + m, ymin - m, ymax + m
    else:  # AUTO
        cg, _ = _center_of_gravity(body, plan, top_z)
        half = cg.z * math.tan(math.radians(foot.tip_angle_deg))    # нужный полупролёт опоры
        mm = foot.min_margin
        left = min(xmin - mm, cg.x - half)
        right = max(xmax + mm, cg.x + half)
        front = min(ymin - mm, cg.y - half)
        back = max(ymax + mm, cg.y + half)
        App.Console.PrintMessage(
            f"[foot] auto: ЦТ=({cg.x:.1f},{cg.y:.1f},{cg.z:.1f}) полупролёт>={half:.1f} мм\n"
        )

    slab = Part.makeBox(right - left, back - front, foot.thickness, App.Vector(left, front, 0))
    if foot.chamfer > 0:
        slab = _chamfer_bottom(slab, foot.chamfer)
    return slab


def _chamfer_bottom(slab: Part.Shape, size: float) -> Part.Shape:
    """Best-effort фаска по нижним кромкам плиты (при неудаче — без фаски)."""
    try:
        bottom_edges = [e for e in slab.Edges
                        if all(abs(v.Z) < 1e-6 for v in e.Vertexes)]
        return slab.makeChamfer(size, bottom_edges)
    except Exception as exc:  # noqa: BLE001
        App.Console.PrintWarning(f"[foot] фаску не удалось сделать: {exc}\n")
        return slab
