"""Крышка-колпак над торчащими свёрлами (отдельная печатная деталь).

Колпак надевается сверху на корпус: внутренняя полость = габарит корпуса + зазор, высота = по
самому высокому сверлу + зазор. Съёмный (REMOVABLE) — 4 стенки; обод юбки садится на опорный
буртик-уступ корпуса (вертикальная опора, нагрузка в корпус/плиту), плюс опциональные рёбра-
защёлки по низу передней/задней юбки с ответными канавками в торцах корпуса (держат от подъёма).
Откидной (HINGED) — без передней (фасадной) стенки и без переднего свеса крыши (козырька);
боковые стенки продлены сплошняком до самого низа корпуса, нижне-задний угол скруглён вокруг
отверстия под ось (петля прямо в стенке). По бокам корпуса — круглые оси (штыри). Закрытое
положение фиксируется защёлками на боковых стенках спереди.
"""

from __future__ import annotations

from typing import Optional, Tuple

import FreeCAD as App
import Part

from ..model import LidMode, LidSpec

_X = App.Vector(1, 0, 0)
_Y = App.Vector(0, 1, 0)

_SNAP_CLEAR = 0.2   # зазор канавки вокруг детента, мм (лёгкая защёлка под FDM)
_SNAP_LEN = 8.0     # длина детента/канавки вдоль Y, мм


def make_lid(
    body: Part.Shape, lid: LidSpec, top_z: float, max_protrusion: float,
    hinge_floor: float = 0.0, side_margin: float = 1e9,
) -> Tuple[Part.Shape, Optional[Part.Shape], Optional[Part.Shape]]:
    """Вернуть ``(lid_shape, body_add, body_cut)``.

    ``body_add`` — что приварить к корпусу (оси-штыри откидной крышки) или ``None``;
    ``body_cut`` — что вырезать из корпуса (канавки-выемки под защёлки крышки) или ``None``.

    ``hinge_floor`` — нижний предел для оси откидной крышки по Z (верх плиты основания, если она
    есть): ось и петлю держим выше него, чтобы не сталкиваться с выносом плиты.
    ``side_margin`` — гарантированная толщина бока холдера от грани до ближайшего гнезда
    (``layout.edge_margin``): глубину канавок-выемок ограничиваем ею, чтобы не прорезать в гнездо.
    """
    bb = body.BoundBox
    c, w = lid.clearance, lid.wall

    # Прямоугольники полости (по корпусу + зазор) и наружного контура (+ стенка).
    in_x0, in_x1 = bb.XMin - c, bb.XMax + c
    in_y0, in_y1 = bb.YMin - c, bb.YMax + c
    out_x0, out_x1 = in_x0 - w, in_x1 + w
    out_y0, out_y1 = in_y0 - w, in_y1 + w

    skirt_bottom = top_z - lid.skirt              # докуда юбка заходит на бока корпуса
    if lid.mode is LidMode.REMOVABLE:
        skirt_bottom = max(skirt_bottom, hinge_floor)  # юбка не уходит ниже опорной плиты (foot)
    panel_inner = top_z + max_protrusion + lid.top_gap  # низ верхней панели (над свёрлами)
    panel_outer = panel_inner + w

    outer = _box(out_x0, out_y0, skirt_bottom, out_x1, out_y1, panel_outer)
    inner = _box(in_x0, in_y0, skirt_bottom, in_x1, in_y1, panel_inner)
    cap = outer.cut(inner)

    if lid.mode is LidMode.REMOVABLE:
        # Опорный буртик: корпус расширен до наружной грани юбки от плиты (hinge_floor) до низа юбки —
        # колпак садится ободом юбки на его верх, вертикальная опора есть всегда. Нагрузка идёт
        # корпус→плита→стол, а не на свёрла или защёлки (те только держат от подъёма).
        shoulder = _seat_shoulder(
            out_x0, out_y0, out_x1, out_y1, bb.XMin, bb.YMin, bb.XMax, bb.YMax,
            hinge_floor, skirt_bottom,
        )
        recess = None
        if lid.snap and lid.snap_protrusion > 0:
            cap, recess = _add_snaps(cap, in_x0, in_x1, in_y0, in_y1, skirt_bottom, side_margin, lid)
        return cap, shoulder, recess

    # HINGED: убрать переднюю стенку ЦЕЛИКОМ, включая передний свес верхней панели (до panel_outer),
    # иначе крыша нависает козырьком над открытым передом. Режем по ЛИЦЕВОЙ плоскости холдера (bb.YMin),
    # а не по переду полости (in_y0): перёд открыт, боковым стенкам спереди клириться не обо что, поэтому
    # зазор c там лишний — иначе стенки торчат на c вперёд за лицо корпуса.
    front = bb.YMin                                # лицевая плоскость холдера
    cap = cap.cut(_box(out_x0 - 1, out_y0 - 1, skirt_bottom - 1, out_x1 + 1, front, panel_outer + 1.0))

    r_pin = lid.pin_diameter / 2.0
    r_hole = r_pin + lid.hinge_clearance
    ring = max(1.2, lid.ear_thickness)             # материал-кольцо вокруг оси (радиус скругления угла)
    R_ear = r_hole + ring

    # Ось — НИЗКО и СЗАДИ, в скруглённом нижне-заднем углу боковой стенки (флип-бэк, откидывается назад).
    # Низ стенок ставим РОВНО на верх плиты основания (hinge_floor) — стенки опираются на неё, держится
    # надёжнее. Ось на R_ear над низом и впереди задней грани: скруглённый угол радиуса R_ear касается и
    # низа (плиты), и зада, а ось сидит в его центре. При откидывании дуга угла идёт по окружности вокруг
    # оси и не опускается ниже z_floor — то есть касается плиты, но не врезается.
    z_floor = hinge_floor                           # низ боковых стенок — на верхе плиты (без щели)
    z_hinge = min(skirt_bottom - 1.0, z_floor + R_ear)
    y_hinge = out_y1 - R_ear

    pin_len = max(lid.pin_length, c + w + 1.0)      # ось должна пройти зазор и стенку
    if pin_len > lid.pin_length:
        App.Console.PrintMessage(f"[lid] pin_length увеличен до {pin_len:.1f} мм (зазор+стенка)\n")

    # Продлить СУЩЕСТВУЮЩИЕ боковые стенки вниз до z_floor сплошняком (от переда in_y0 до зада out_y1),
    # затем скруглить нижне-задний угол: вырезаем квадратный угол и возвращаем четвертькруг радиуса R_ear.
    # Верх перекрывает юбку на 1 мм — слияние в одну стенку без шва.
    for x_out, x_in in ((out_x0, in_x0), (in_x1, out_x1)):
        rect = _box(x_out, front, z_floor, x_in, out_y1, skirt_bottom + 1.0)
        corner = _box(x_out - 1, y_hinge, z_floor - 1, x_in + 1, out_y1 + 1, z_hinge)  # квадратный нижне-задний угол
        disk = Part.makeCylinder(R_ear, w, App.Vector(x_out, y_hinge, z_hinge), _X)    # четвертькруг скругления
        cap = cap.fuse(rect.cut(corner).fuse(disk))

    # Отверстия под оси — в центре скруглённого угла, сквозь боковую стенку.
    for x_start in (out_x0 - 1.0, in_x1 - 1.0):
        hole = Part.makeCylinder(r_hole, w + 2.0, App.Vector(x_start, y_hinge, z_hinge), _X)
        cap = cap.cut(hole)

    # Фиксация закрытого положения: горизонтальные детенты на боковых стенках спереди + ответные
    # канавки-выемки в боках холдера (возвращаются в body_cut). Детент горизонтален (вдоль Y), чтобы
    # держать передний край от подъёма при откидывании: чтобы открыть, ребро выщёлкивается из канавки.
    recess = None
    if lid.snap and lid.snap_protrusion > 0:
        cap, recess = _side_snaps(cap, bb, c, in_x0, in_x1, front, z_floor, side_margin, lid)

    # Оси (штыри) на боках корпуса; утоплены на embed внутрь, иначе не сплавятся с корпусом.
    embed = 1.0
    right = Part.makeCylinder(r_pin, pin_len + embed, App.Vector(bb.XMax - embed, y_hinge, z_hinge), _X)
    left = Part.makeCylinder(r_pin, pin_len + embed, App.Vector(bb.XMin - pin_len, y_hinge, z_hinge), _X)
    return cap, right.fuse(left), recess


def _box(x0, y0, z0, x1, y1, z1) -> Part.Shape:
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, App.Vector(x0, y0, z0))


def _seat_shoulder(
    out_x0, out_y0, out_x1, out_y1, body_x0, body_y0, body_x1, body_y1, floor_z, seat_z,
) -> Optional[Part.Shape]:
    """Опорный буртик-уступ под обод юбки съёмного колпака (солид для fuse в корпус).

    Это РАМКА-кольцо СНАРУЖИ корпуса (наружу до грани юбки ``out_*``, внутрь — до грани корпуса
    ``body_*``), от опорной плиты (``floor_z``: верх foot, либо 0 = стол) до низа юбки (``seat_z``).
    Колпак садится ободом на её верх: вертикальная опора есть всегда, колпак не висит на защёлках и
    не падает на свёрла. ВАЖНО: footprint корпуса вычитается — иначе сплошной бокс при fuse засыпал
    бы гнёзда снизу до ``seat_z`` (гнёзда сверлятся от верхней грани вниз). Низ опускаем на 0.5 мм в
    плиту (если есть) — чистый union без копланарного шва. Возвращает ``None``, если уступа
    практически нет (юбка и так достаёт до плиты/стола)."""
    bottom = max(0.0, floor_z - 0.5)
    if seat_z - bottom < 0.6:
        return None
    ring = _box(out_x0, out_y0, bottom, out_x1, out_y1, seat_z)
    core = _box(body_x0, body_y0, bottom - 1.0, body_x1, body_y1, seat_z + 1.0)  # footprint корпуса
    return ring.cut(core)


_SNAP_MIN_WALL = 1.0  # минимальная перемычка корпуса под канавкой, мм
_SNAP_MIN_ENG = 0.2   # минимальный осмысленный зацеп детента, мм


def _side_snaps(cap, bb, c, in_x0, in_x1, front, z_floor, side_margin, lid: LidSpec):
    """Горизонтальные детенты на боковых стенках спереди + ответные канавки-выемки в боках холдера.

    Детент — горизонтальный валик (ось Y) по внутренней грани стенки, выступающий внутрь так, что
    его вершина заходит за грань корпуса на зацеп ``eng``. В корпусе под него — канавка той же оси,
    чуть шире (``_SNAP_CLEAR``): валик садится в неё. Чтобы откинуть крышку, передний край
    поднимается — валик выщёлкивается из канавки через её верхнюю кромку (требует отгиба стенки).

    Глубина канавки в корпус = ``eng + _SNAP_CLEAR`` ограничена толщиной бока (``side_margin``),
    чтобы оставить перемычку ``_SNAP_MIN_WALL`` и не прорезать в гнездо. Тонкий холдер — мягко
    уменьшаем зацеп (или вовсе пропускаем защёлки) с жёлтым предупреждением, а не ломаем геометрию.

    Возвращает ``(cap, recess)``; ``recess`` (или ``None``) нужно вырезать из корпуса.
    """
    avail = side_margin - _SNAP_MIN_WALL            # сколько можно врезать в бок, оставив перемычку
    eng = min(lid.snap_protrusion, avail - _SNAP_CLEAR)
    if eng < _SNAP_MIN_ENG:
        App.Console.PrintWarning(
            f"[lid] тонкий бок холдера (edge_margin={side_margin:.1f} мм): места под выемку-защёлку "
            f"нет — защёлки пропущены, крышку держит петля. Увеличьте layout.edge_margin для защёлок.\n"
        )
        return cap, None
    if eng < lid.snap_protrusion - 1e-9:
        App.Console.PrintWarning(
            f"[lid] тонкий бок холдера: зацеп защёлки уменьшен с {lid.snap_protrusion:.2f} до "
            f"{eng:.2f} мм (чтобы оставить перемычку {_SNAP_MIN_WALL:.1f} мм над гнездом).\n"
        )

    z_snap = z_floor + 4.0                          # низко-спереди: дальше от оси → сильнее держит
    y0 = front + 2.0
    r_rib = c + eng                                 # валик от грани стенки до +eng в корпус
    r_grv = r_rib + _SNAP_CLEAR
    recesses = []
    for x_face in (in_x0, in_x1):                   # внутренние грани левой и правой стенок
        rib = Part.makeCylinder(r_rib, _SNAP_LEN, App.Vector(x_face, y0, z_snap), _Y)
        cap = cap.fuse(rib)
        recesses.append(Part.makeCylinder(r_grv, _SNAP_LEN, App.Vector(x_face, y0, z_snap), _Y))
    return cap, recesses[0].fuse(recesses[1])


def _add_snaps(cap, in_x0, in_x1, in_y0, in_y1, skirt_bottom, front_margin, lid: LidSpec):
    """Рёбра-защёлки по низу передней и задней юбки + ответные канавки в торцах корпуса.

    Ребро — горизонтальный валик (ось X) по внутренней грани передней/задней стенки; его вершина
    заходит за грань корпуса на зацеп ``eng``. В торце корпуса под него — канавка той же оси, чуть
    шире (``_SNAP_CLEAR``): при надевании валик садится в неё со щелчком, при снятии выщёлкивается
    (стенка отгибается). Без канавки (как было раньше) выступ ``snap_protrusion`` целиком съедал
    зазор ``clearance`` — реальный зацеп выходил ~0.1 мм и защёлки фактически не было.

    Глубина канавки = ``eng + _SNAP_CLEAR`` ограничена ``front_margin`` (расстояние от торца корпуса
    до ближайшего гнезда), чтобы оставить перемычку ``_SNAP_MIN_WALL`` и не прорезать в гнездо.
    Тонкий торец — мягко уменьшаем зацеп (или вовсе пропускаем защёлки) с жёлтым предупреждением.

    Возвращает ``(cap, recess)``; ``recess`` (или ``None``) нужно вырезать из корпуса.
    """
    avail = front_margin - _SNAP_MIN_WALL           # сколько можно врезать в торец, оставив перемычку
    eng = min(lid.snap_protrusion, avail - _SNAP_CLEAR)
    if eng < _SNAP_MIN_ENG:
        App.Console.PrintWarning(
            f"[lid] тонкий торец корпуса (edge_margin={front_margin:.1f} мм): места под выемку-защёлку "
            f"нет — защёлки пропущены, крышка держится трением юбки. Увеличьте layout.edge_margin.\n"
        )
        return cap, None
    if eng < lid.snap_protrusion - 1e-9:
        App.Console.PrintWarning(
            f"[lid] тонкий торец корпуса: зацеп защёлки уменьшен с {lid.snap_protrusion:.2f} до "
            f"{eng:.2f} мм (чтобы оставить перемычку {_SNAP_MIN_WALL:.1f} мм над гнездом).\n"
        )

    z = skirt_bottom + 2.0
    length = (in_x1 - in_x0) * 0.5
    x0 = (in_x0 + in_x1) / 2.0 - length / 2.0
    r_rib = lid.clearance + eng                     # от грани стенки до +eng в корпус (компенсация зазора)
    r_grv = r_rib + _SNAP_CLEAR
    recesses = []
    for y_face in (in_y0, in_y1):                   # внутренние грани передней и задней стенок
        rib = Part.makeCylinder(r_rib, length, App.Vector(x0, y_face, z), _X)
        cap = cap.fuse(rib)
        recesses.append(Part.makeCylinder(r_grv, length, App.Vector(x0, y_face, z), _X))
    return cap, recesses[0].fuse(recesses[1])
