"""Расчёт раскладки гнёзд и разрешение плана — чистая математика без FreeCAD.

Радиальные формулы (радиус гнезда, внешний радиус кармана) живут здесь и переиспользуются
геометрическим слоем, чтобы spacing и реальная геометрия не разъезжались. Результат —
:class:`ResolvedPlan`, который полностью описывает, где и какой глубины каждое гнездо.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import List, Optional, Tuple

from .model import (
    Drill,
    LabelPosition,
    LabelReference,
    LayoutMode,
    ResolvedPlan,
    RowAlign,
    ShankType,
    Socket,
    SpringSpec,
    Specs,
)

# Порог длины (мм), выше которого авто-режим предпочитает наклонную подставку:
# длинные свёрла удобнее доставать и они устойчивее под наклоном.
LONG_DRILL_THRESHOLD = 100.0
# До скольких свёрел авто-режим использует один ряд, дальше — сетку.
ROW_MAX_COUNT = 8


def shank_radius(drill: Drill, specs: Specs) -> float:
    """Номинальный радиус, который занимает хвостовик (без зазоров).

    Для круглого — половина диаметра сверла. Для шестигранного размер хвостовика стандартный
    (``socket.hex_size``, across flats), описанный радиус по вершинам = ``hex_size / sqrt(3)``;
    диаметр сверла ``d`` на hex-гнездо не влияет (только подпись).
    """
    if drill.shank is ShankType.HEX:
        return specs.socket.hex_size / math.sqrt(3.0)
    return drill.d / 2.0


def bore_radius(drill: Drill, specs: Specs) -> float:
    """Описанный радиус посадочного отверстия с учётом зазора (для hex — радиус по вершинам)."""
    if drill.shank is ShankType.HEX:
        return shank_radius(drill, specs) + specs.socket.hex_clearance
    return shank_radius(drill, specs) + specs.socket.clearance


def socket_outer_radius(drill: Drill, specs: Specs) -> float:
    """Внешний радиус вырезаемого материала — для расчёта шага и положения подписей.

    Пружины-детенты есть и у круглых, и у hex-гнёзд (они дают осевую фиксацию — чтобы хвостовик
    не выпадал). Крайняя удаляемая поверхность — дно ниши за лепестком. Для круглого ниша
    отсчитывается от ``bore`` (описанного радиуса), для hex — от апофемы грани (``bore·√3/2``);
    берём максимум с вершиной hex, т.к. угол призмы (``bore``) может торчать дальше неглубокой ниши.
    Без пружин — само посадочное отверстие.
    """
    if not specs.springs.enabled:
        return bore_radius(drill, specs)
    back = specs.springs.leaf_thickness + specs.springs.relief_gap
    if drill.shank is ShankType.HEX:
        rc = bore_radius(drill, specs)               # описанный радиус (вершина призмы)
        apothem = rc * math.sqrt(3.0) / 2.0          # грань, на которой сидит детент
        return max(rc, apothem + back)
    return bore_radius(drill, specs) + back


# Ширина одного символа подписи как доля высоты шрифта — грубая оценка места под текст в раскладке
# (точные метрики знает только FreeCAD при сборке). Берём с запасом, чтобы подписи гарантированно
# не наезжали на соседние гнёзда/подписи и помещались на корпусе.
_LABEL_CHAR_W = 0.7

# Стороны габарита относительно осей: front=−Y, back=+Y, left=−X, right=+X.
_LABEL_SIDE = {
    LabelPosition.FRONT: "front",
    LabelPosition.BACK: "back",
    LabelPosition.LEFT: "left",
    LabelPosition.RIGHT: "right",
}


def _label_text(drill: Drill) -> str:
    """Текст подписи как в geometry: явная метка или диаметр без хвостовых нулей."""
    return (drill.label or "").strip() or f"{drill.d:.2f}".rstrip("0").rstrip(".")


def _label_span(drill: Drill, specs: Specs) -> Tuple[float, float]:
    """Оценка габарита подписи ``(вдоль выноса, поперёк)`` в мм; ``(0, 0)`` если подписи выключены."""
    lab = specs.labels
    if not lab.enabled:
        return 0.0, 0.0
    height = lab.size
    width = len(_label_text(drill)) * _LABEL_CHAR_W * lab.size
    if lab.position in (LabelPosition.LEFT, LabelPosition.RIGHT):
        return width, height   # вынос по X: вдоль = ширина текста, поперёк = высота
    return height, width       # вынос по Y: вдоль = высота, поперёк = ширина текста


_MIN_LEAF_WIDTH = 0.8     # минимально печатаемая/осмысленная ширина лепестка, мм (≈2 сопла)
_MAX_LEAF_ARC_DEG = 120.0  # лепесток не оборачивает больше — остаётся язычком, а не полукольцом
_FIT_MARGIN_DEG = 6.0      # угловой запас между соседними лепестками по окружности


def _fit_rows(depth: float, springs: SpringSpec) -> int:
    """Сколько рядов пружин влезает по глубине ЭТОГО гнезда (ряды + заделки у концов).

    Формула зеркалит ``geometry.socket.spring_stations``: ряд занимает ``leaf_length``, между и по
    краям — заделки ``anchor``. Возвращает 0, если не лезет даже один ряд (гнездо слишком мелкое)."""
    L = springs.leaf_length
    anchor = max(1.0, springs.slot_width)
    span = depth - min(0.8, depth * 0.1)
    for rw in range(springs.rows, 0, -1):
        if rw * L + (rw + 1) * anchor <= span:
            return rw
    return 0


def fit_springs(drill: Drill, depth: float, specs: Specs) -> Optional[SpringSpec]:
    """Подогнать пружины-детенты под КОНКРЕТНОЕ гнездо (а не урезать всё до худшего сверла).

    ``springs.count``/``rows`` трактуются как ЖЕЛАЕМЫЙ МАКСИМУМ: каждое гнездо берёт по максимуму
    влезающего. Для круглого бора ширина лепестка ``leaf_width`` ужимается под дугу, так что мелкое
    сверло получает узкий язычок с тем же детентом (зажим ``bump_protrusion − clearance`` от диаметра
    не зависит), а не «нет пружин» и не тащит крупные гнёзда вниз. Hex от диаметра не зависит (грань
    задана ``hex_size``): детентов ≤ 6, лепесток по ширине грани.

    Возвращает ужатую спеку либо ``None`` — пружины для гнезда не строятся (выключены глобально,
    гнездо мельче одного ряда, или не лезет ни один печатаемый лепесток). ``None`` → гладкий бор."""
    springs = specs.springs
    if not springs.enabled:
        return None
    rows = _fit_rows(depth, springs)
    if rows < 1:
        return None

    if drill.shank is ShankType.HEX:
        flat = bore_radius(drill, specs)                 # сторона hex = описанный радиус
        leaf_w = min(springs.leaf_width, flat - 3.0 * springs.slot_width)  # лепесток + 2 пропила + запас
        if leaf_w < _MIN_LEAF_WIDTH:
            return None
        return replace(springs, count=min(springs.count, 6), rows=rows, leaf_width=leaf_w)

    # Круг: наибольший count ≤ желаемого, при котором лепесток остаётся печатаемым язычком,
    # ужимая ширину под доступную на один лепесток дугу (360/count − два пропила − запас).
    r = bore_radius(drill, specs)
    slot_ang = math.degrees(springs.slot_width / r)
    for count in range(springs.count, 0, -1):
        leaf_ang = min(_MAX_LEAF_ARC_DEG, 360.0 / count - 2.0 * slot_ang - _FIT_MARGIN_DEG)
        if leaf_ang <= 0:
            continue
        leaf_w = min(springs.leaf_width, r * math.radians(leaf_ang))
        if leaf_w >= _MIN_LEAF_WIDTH:
            return replace(springs, count=count, rows=rows, leaf_width=leaf_w)
    return None


def socket_extents(drill: Drill, specs: Specs) -> dict:
    """Полугабариты «гнездо + его подпись» от центра по сторонам (front/back/left/right), мм.

    Подпись выносится за гнездо в направлении ``labels.position`` и центрируется поперёк него.
    Возврат — словарь сторон; используется и упаковкой (чтобы подписям хватало места между
    гнёздами и рядами), и расчётом корпуса (чтобы подпись не свисала с грани). Без подписей —
    все стороны равны внешнему радиусу гнезда.
    """
    r = socket_outer_radius(drill, specs)
    # Декоративное колечко облегает само отверстие (от bore + зазор) и уходит наружу на width.
    # Если его внешняя кромка выходит за край гнезда — резервируем место со всех сторон, чтобы
    # соседние колечки (и края корпуса) не наезжали. Якорь подписи остаётся от края гнезда (как в
    # geometry/labels), поэтому колечко учитываем отдельной базой, а не сдвигом r.
    ring_r = r
    if specs.rings.enabled:
        ring_r = max(r, bore_radius(drill, specs) + specs.rings.gap + specs.rings.width)
    ext = {"front": ring_r, "back": ring_r, "left": ring_r, "right": ring_r}
    lab = specs.labels
    if not lab.enabled:
        return ext
    along, perp = _label_span(drill, specs)
    anchor = r if lab.reference is LabelReference.EDGE else 0.0
    reach = anchor + lab.offset + along         # дальняя кромка текста от центра
    half = perp / 2.0                            # текст центрирован поперёк направления выноса
    side = _LABEL_SIDE[lab.position]
    ext[side] = max(ext[side], reach)
    if lab.position in (LabelPosition.FRONT, LabelPosition.BACK):
        ext["left"] = max(ext["left"], half)
        ext["right"] = max(ext["right"], half)
    else:
        ext["front"] = max(ext["front"], half)
        ext["back"] = max(ext["back"], half)
    return ext


def resolve_depth(drill: Drill, specs: Specs) -> float:
    """Глубина гнезда = доля от длины сверла, ограниченная min/max."""
    s = specs.socket
    raw = drill.length * s.depth_ratio
    return max(s.min_depth, min(s.max_depth, raw))


def recommend_mode(drills: List[Drill]) -> LayoutMode:
    """Эвристика выбора режима для ``mode="auto"``.

    Длинные свёрла → наклонная подставка; иначе ряд до :data:`ROW_MAX_COUNT`, далее сетка.
    """
    if any(d.length >= LONG_DRILL_THRESHOLD for d in drills):
        return LayoutMode.ANGLED
    if len(drills) <= ROW_MAX_COUNT:
        return LayoutMode.ROW
    return LayoutMode.GRID


def _row_offset(r: float, r_max: float, align: RowAlign) -> float:
    """Поперечное смещение центра гнезда (по Y) для выбранной линии выравнивания.

    Крупнейшее гнездо всегда остаётся на оси (y=0); остальные сдвигаются так, чтобы совпали
    их края. FRONT (−Y) выстраивает ближние кромки (``y − r = −r_max``), BACK — дальние
    (``y + r = +r_max``), CENTER оставляет оси на одной линии.
    """
    if align is RowAlign.FRONT:
        return r - r_max
    if align is RowAlign.BACK:
        return r_max - r
    return 0.0


def _packed_x(lefts: List[float], rights: List[float], pitch_extra: float) -> List[float]:
    """X-координаты центров вдоль линии по асимметричным полугабаритам.

    Шаг между центрами = правый полугабарит левого соседа + ``pitch_extra`` + левый полугабарит
    правого. Адаптивно (мелкие гнёзда не занимают место крупных) и с учётом подписи: ``lefts``/
    ``rights`` уже включают вынос текста вбок. Левая кромка первого — на x=0.
    """
    xs: List[float] = []
    x = lefts[0] if lefts else 0.0
    for i in range(len(lefts)):
        if i > 0:
            x += rights[i - 1] + pitch_extra + lefts[i]
        xs.append(x)
    return xs


def _row_data(drills: List[Drill], specs: Specs):
    """Подготовить данные ряда без абсолютного X.

    Возвращает ``(exts, ys, natural)``: полугабариты «гнездо+подпись» по сторонам, Y-смещения по
    ``layout.align`` (вокруг оси полосы) и «естественную» ширину ряда (сумма габаритов + зазоры).
    """
    exts = [socket_extents(d, specs) for d in drills]
    radii = [socket_outer_radius(d, specs) for d in drills]
    r_max = max(radii) if radii else 0.0
    ys = [_row_offset(r, r_max, specs.layout.align) for r in radii]
    content = sum(e["left"] + e["right"] for e in exts)
    natural = content + max(0, len(drills) - 1) * specs.layout.pitch_extra
    return exts, ys, natural


def _row_yspan(exts, ys) -> Tuple[float, float]:
    """Вынос ряда вперёд (−Y) и назад (+Y) от оси полосы с учётом смещений и подписей."""
    front = max((e["front"] - y for e, y in zip(exts, ys)), default=0.0)
    back = max((e["back"] + y for e, y in zip(exts, ys)), default=0.0)
    return front, back


def _spread_x(exts, width: float) -> List[float]:
    """X-центры по принципу CSS flex ``space-around``: ряд растянут на ``width`` и центрирован.

    Свободное место (``width − сумма габаритов``) делится поровну на ``n`` промежутков — по половине
    с каждой стороны гнезда, так что краевые отступы вдвое меньше внутренних. Узкие ряды
    распределяются по всей ширине и центрируются на ``width/2``, а не липнут к левому краю.
    """
    n = len(exts)
    if n == 0:
        return []
    content = sum(e["left"] + e["right"] for e in exts)
    gap = (width - content) / n
    xs: List[float] = []
    cursor = gap / 2.0
    for e in exts:
        xs.append(cursor + e["left"])           # левая кромка габарита на cursor, центр — +left
        cursor += e["left"] + e["right"] + gap
    return xs


def _row_positions(drills: List[Drill], specs: Specs) -> List[Tuple[float, float]]:
    """Один ряд: адаптивная упаковка по X слева (зазор ``pitch_extra``); по Y — ``layout.align``.

    Шаг учитывает и размер гнёзд, и боковой вынос подписей, чтобы соседние подписи не наезжали.
    """
    exts, ys, _natural = _row_data(drills, specs)
    xs = _packed_x([e["left"] for e in exts], [e["right"] for e in exts], specs.layout.pitch_extra)
    return list(zip(xs, ys))


def _grid_positions(drills: List[Drill], specs: Specs) -> List[Tuple[float, float]]:
    """Адаптивная сетка: ряды складываются по Y, а по X растягиваются на общую ширину и
    центрируются по принципу CSS flex ``space-around``.

    Общая ширина = «естественная» ширина самого широкого ряда. Узкие ряды распределяются равными
    промежутками вокруг гнёзд (а не липнут к левому краю), все ряды центрированы по одной оси. По Y
    ряды складываются с зазором, учитывающим вынос подписей; внутри ряда работает ``layout.align``.

    При ``layout.serpentine`` нечётные ряды раскладываются справа налево («змейкой»): свёрла
    отсортированы по размеру, и разворот делает их размерный ряд непрерывным — конец одного ряда и
    начало следующего оказываются соседями по вертикали, без скачка размера на переносе.
    """
    n = len(drills)
    cols = specs.layout.grid_cols or max(1, math.ceil(math.sqrt(n)))
    row_gap = specs.layout.row_gap
    serpentine = specs.layout.serpentine
    rows = [drills[i : i + cols] for i in range(0, n, cols)]
    data = [_row_data(r, specs) for r in rows]
    width = max((natural for _exts, _ys, natural in data), default=0.0)  # ширина широчайшего ряда

    positions: List[Tuple[float, float]] = []
    y_cursor = 0.0  # передняя (−Y) граница текущего ряда
    for ri, (exts, ys, _natural) in enumerate(data):
        # Физический порядок гнёзд вдоль X: на нечётных рядах — обратный (змейка). Габариты
        # раскладываем в этом порядке (чтобы зазоры/подписи считались по реальным соседям), затем
        # возвращаем X каждому гнезду на его исходный индекс — ys и нумерация гнёзд не меняются.
        order = list(range(len(exts)))
        if serpentine and ri % 2 == 1:
            order.reverse()
        xs_phys = _spread_x([exts[k] for k in order], width)
        xs = [0.0] * len(exts)
        for slot, k in enumerate(order):
            xs[k] = xs_phys[slot]
        front, back = _row_yspan(exts, ys)
        center = y_cursor + front
        positions.extend((x, center + y) for x, y in zip(xs, ys))
        y_cursor = center + back + row_gap
    return positions


def compute_positions(
    drills: List[Drill], specs: Specs, mode: LayoutMode
) -> List[Tuple[float, float]]:
    """Координаты центров гнёзд в плоскости верхней грани для заданного режима.

    ``angled`` раскладывается как ряд: наклон верхней грани добавляет геометрический слой.
    """
    if not drills:
        return []
    if mode is LayoutMode.GRID:
        return _grid_positions(drills, specs)
    # ROW и ANGLED используют линейную раскладку (наклон применяется в geometry).
    return _row_positions(drills, specs)


def resolve_plan(drills: List[Drill], specs: Specs) -> ResolvedPlan:
    """Собрать полностью разрешённый план: режим, отсортированные гнёзда, позиции и глубины."""
    mode = specs.layout.mode
    if mode is LayoutMode.AUTO:
        mode = recommend_mode(drills)

    # Сортируем по РЕАЛЬНОМУ размеру гнезда (внешнему радиусу), а не по диаметру сверла: у hex
    # гнездо считается от socket.hex_size, поэтому «5 hex» (гнездо под ключ ≈6.35) больше «6 round».
    # Тай-брейк по диаметру — детерминированный порядок при равных гнёздах. Так ряд идёт строго
    # от меньшего отверстия к большему.
    ordered = sorted(drills, key=lambda d: (socket_outer_radius(d, specs), d.d))
    positions = compute_positions(ordered, specs, mode)

    sockets = [
        Socket(
            drill=d,
            x=x,
            y=y,
            depth=resolve_depth(d, specs),
            outer_radius=socket_outer_radius(d, specs),
        )
        for d, (x, y) in zip(ordered, positions)
    ]
    return ResolvedPlan(sockets=sockets, specs=specs, resolved_mode=mode)
