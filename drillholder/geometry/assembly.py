"""Сборка модели: корпус − гнёзда ± подписи, плюс основание и крышка.

Принимает разрешённый план из ядра, строит корпус, размещает на рабочей грани инструменты
гнёзд (с учётом наклона) и вычитает их, приваривает детенты пружин, наносит подписи (вычитает
для гравировки или приваривает для выдавливания; при ``labels.multicolor`` — выносит подписи
отдельной деталью «Labels» под печать другим пластиком, оставляя в корпусе выемки) и опционально
утапливает заподлицо декоративные колечки вокруг гнёзд (деталь «Rings», тоже второй пластик). Затем
по конфигу добавляет устойчивое основание (вфьюзивается в корпус) и крышку (отдельная деталь).
Возвращает документ FreeCAD и список деталей ``[(name, feature), ...]``.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import FreeCAD as App
import Part

from ..fonts import resolve_font_detailed
from ..layout import bore_radius
from ..model import FootMode, LabelMode, LidMode, ResolvedPlan
from .base import make_base
from .foot import make_foot
from .labels import make_label
from .lid import make_lid
from .rings import make_ring
from .socket import make_socket


def _place_on_surface(shape: Part.Shape, socket, surface) -> Part.Shape:
    """Поставить каноническую форму (устье на z=depth) устьем на грань, осью по нормали."""
    placed = shape.copy()
    # Оператор '-'/'*' даёт новый вектор; Vector.sub/multiply мутируют общий surface.normal.
    base = surface.point(socket.x, socket.y) - surface.normal * socket.depth
    placed.Placement = App.Placement(base, surface.rotation)
    return placed


def _build_body(
    plan: ResolvedPlan, doc
) -> Tuple[Part.Shape, object, List[Tuple[str, Part.Shape]]]:
    """Корпус с гнёздами, пружинами, подписями и колечками (без основания и крышки).

    Возвращает ``(solid, surface, inlays)`` — рабочую грань отдаём наружу, чтобы опциональная
    деталь «Drills» размещала свёрла тем же преобразованием, не пересобирая корпус. ``inlays`` —
    список ``(name, shape)`` инкрустаций под печать вторым пластиком (подписи при ``multicolor``,
    декоративные колечки): они не сливаются с корпусом, а в корпусе под них вырезаются выемки.
    """
    specs = plan.specs
    solid, surface = make_base(plan)

    for socket in plan.sockets:
        cut, add = make_socket(socket, specs)
        solid = solid.cut(_place_on_surface(cut, socket, surface))
        if add is not None:
            solid = solid.fuse(_place_on_surface(add, socket, surface))

    inlays: List[Tuple[str, Part.Shape]] = []
    solid, labels = _apply_labels(plan, doc, solid, surface)
    if labels is not None:
        inlays.append(("Labels", labels))
    solid, rings = _apply_rings(plan, solid, surface)
    if rings is not None:
        inlays.append(("Rings", rings))
    return solid, surface, inlays


def _apply_labels(plan, doc, solid: Part.Shape, surface) -> Tuple[Part.Shape, Optional[Part.Shape]]:
    """Нанести подписи на корпус. Вернуть ``(solid, labels)``: ``labels`` — отдельная деталь при
    ``labels.multicolor`` (текст вторым пластиком, в корпусе выемки), иначе ``None`` (текст слит)."""
    specs = plan.specs
    if not specs.labels.enabled:
        return solid, None
    result = resolve_font_detailed(specs.labels.font)
    font = result.path
    if font is None:
        App.Console.PrintWarning("[labels] не найдено ни одного шрифта — подписи пропущены\n")
        return solid, None
    if not result.honored:
        # Жёлтое предупреждение только при реальном откате: запрошенный шрифт не найден.
        App.Console.PrintWarning(
            f"[labels] шрифт '{specs.labels.font}' не найден (ни файл, ни системный); "
            f"использую запасной: {font}\n"
        )
    elif not specs.labels.font:
        # Пустое поле — штатное «авто», спокойное сообщение без жёлтого.
        App.Console.PrintMessage(f"[labels] шрифт не задан — использую системный: {font}\n")
    emboss = specs.labels.mode is LabelMode.EMBOSS
    separate = specs.labels.multicolor
    collected: List[Part.Shape] = []
    for socket in plan.sockets:
        label = make_label(doc, socket, surface, specs.labels, font)
        if label is None:
            continue
        if separate:
            # Многоцветная печать: текст — отдельная деталь, в корпусе вырезаем посадочное место
            # (и для гравировки, и для рельефа — у emboss уходит «корень» _EMBOSS_EMBED, оставляя
            # неглубокую выемку под язычок текста). Печатается другим пластиком, садится заподлицо.
            solid = solid.cut(label)
            collected.append(label)
        else:
            solid = solid.fuse(label) if emboss else solid.cut(label)
    if not collected:
        return solid, None
    return solid, collected[0] if len(collected) == 1 else Part.makeCompound(collected)


def _apply_rings(plan, solid: Part.Shape, surface) -> Tuple[Part.Shape, Optional[Part.Shape]]:
    """Утопить декоративные колечки вокруг гнёзд заподлицо. Вернуть ``(solid, rings)``.

    Кольцо точно подгоняется к корпусу пересечением (``common``): из него выпадает фаска устья,
    пропилы пружин и любые уже вырезанные выемки (подписи, соседние гнёзда) — деталь садится
    заподлицо без нависаний. Корпус режется тем же кольцом. ``rings`` — деталь под второй пластик
    или ``None``, если колечки выключены / ни одно не легло на тело.
    """
    specs = plan.specs
    if not specs.rings.enabled:
        return solid, None
    collected: List[Part.Shape] = []
    for socket in plan.sockets:
        ring = make_ring(socket, specs.rings, surface, bore_radius(socket.drill, specs))
        fill = ring.common(solid)  # ровно та часть кольца, что попадает в тело → заподлицо
        if fill.isNull() or not fill.Solids:
            continue
        solid = solid.cut(ring)
        collected.append(fill)
    if not collected:
        return solid, None
    return solid, collected[0] if len(collected) == 1 else Part.makeCompound(collected)


def _build_drills(plan: ResolvedPlan, surface) -> Optional[Part.Shape]:
    """Деталь «Drills»: модели всех свёрел, размещённые на грани и слитые между собой.

    НЕ сливается с корпусом — отдельное тело (его удобно скрыть/показать, печатать не нужно).
    Ленивый импорт модуля геометрии сверла. Сбой одного сверла не валит деталь: оно пропускается
    с предупреждением. Возвращает ``None``, если ни одно сверло не построилось.
    """
    from .drill import make_drill_model  # ленивый импорт (FreeCAD-слой)
    from ..model import DrillStyle

    n = len(plan.sockets)
    hint = " (спираль — может занять время)" if plan.specs.drill_geometry.style is DrillStyle.SPIRAL else ""
    App.Console.PrintMessage(f"[drill] строю 3D-модели свёрел: {n} шт.{hint}\n")
    placed: List[Part.Shape] = []
    for socket in plan.sockets:
        try:
            model = make_drill_model(socket, plan.specs)
        except Exception as exc:  # noqa: BLE001 — битое сверло не должно валить всю деталь
            App.Console.PrintWarning(f"[drill] сверло d={socket.drill.d} пропущено: {exc}\n")
            continue
        if model is not None:
            placed.append(_place_on_surface(model, socket, surface))
    if not placed:
        return None
    out = placed[0]
    for s in placed[1:]:
        out = out.fuse(s)
    return out


def build_model(plan: ResolvedPlan, doc=None) -> Tuple[object, List[Tuple[str, object]]]:
    """Построить подставку. Возвращает ``(doc, parts)`` — документ и список ``(name, feature)``."""
    specs = plan.specs
    if doc is None:
        doc = App.newDocument("DrillHolder")

    holder, surface, inlays = _build_body(plan, doc)
    top_z = holder.BoundBox.ZMax
    # Выступ каждого сверла над верхней гранью (для высоты крышки и центра тяжести).
    protrusions = [max(0.0, s.drill.length - s.depth) for s in plan.sockets]
    max_protrusion = max(protrusions) if protrusions else 0.0

    # Крышку и основание считаем от ЧИСТОГО корпуса (без осей и плиты), иначе габарит «уплывёт»:
    # оси должны крепиться к бокам корпуса, а не к широкому краю основания.
    body = holder
    lid_shape = None
    if specs.lid.mode is not LidMode.NONE:
        # Откидная ось опускается к низу корпуса, но должна оставаться выше плиты основания —
        # передаём верх плиты (её толщину), если основание есть.
        hinge_floor = specs.foot.thickness if specs.foot.mode is not FootMode.NONE else 0.0
        lid_shape, body_add, body_cut = make_lid(
            holder, specs.lid, top_z, max_protrusion, hinge_floor, specs.layout.edge_margin
        )
        if body_add is not None:
            body = body.fuse(body_add)
        if body_cut is not None:                     # канавки-выемки под защёлки крышки
            body = body.cut(body_cut)

    if specs.foot.mode is not FootMode.NONE:
        body = body.fuse(make_foot(holder, plan, top_z, max_protrusion))

    parts: List[Tuple[str, object]] = [("Holder", _finalize(doc, "Holder", body))]
    # Инкрустации под второй пластик (подписи при multicolor, декоративные колечки). Корпус уже
    # с выемками под них — детали садятся заподлицо, в слайсере им назначают другой филамент.
    for name, shape in inlays:
        parts.append((name, _finalize(doc, name, shape)))
    if lid_shape is not None:
        parts.append(("Lid", _finalize(doc, "Lid", lid_shape)))

    # Опциональные 3D-модели свёрел — отдельная деталь «Drills», НЕ слитая с корпусом.
    if specs.drill_geometry.enabled:
        drills = _build_drills(plan, surface)
        if drills is not None:
            parts.append(("Drills", _finalize(doc, "Drills", drills)))

    doc.recompute()

    for name, feat in parts:
        bb = feat.Shape.BoundBox
        App.Console.PrintMessage(
            f"[assembly] {name}: габарит={bb.XLength:.1f}x{bb.YLength:.1f}x{bb.ZLength:.1f} мм "
            f"объём={feat.Shape.Volume / 1000.0:.1f} см³ solids={len(feat.Shape.Solids)} "
            f"valid={feat.Shape.isValid()}\n"
        )
    App.Console.PrintMessage(
        f"[assembly] режим={plan.resolved_mode.value} гнёзд={len(plan.sockets)} "
        f"крышка={specs.lid.mode.value} основание={specs.foot.mode.value}\n"
    )
    return doc, parts


def _finalize(doc, name: str, solid: Part.Shape):
    if not solid.isValid():
        App.Console.PrintWarning(f"[assembly] {name}: форма невалидна — removeSplitter()\n")
        solid = solid.removeSplitter()
    feature = doc.addObject("Part::Feature", name)
    feature.Shape = solid
    return feature
