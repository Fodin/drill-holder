"""Тесты чистого слоя раскладки — запускаются обычным Python, без FreeCAD."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drillholder.layout import (  # noqa: E402
    bore_radius,
    recommend_mode,
    resolve_depth,
    resolve_plan,
    shank_radius,
    socket_extents,
    socket_outer_radius,
)
from drillholder.model import (  # noqa: E402
    Drill,
    LabelPosition,
    LabelSpec,
    LayoutMode,
    LayoutSpec,
    RowAlign,
    ShankType,
    SocketSpec,
    SpringSpec,
    Specs,
)

_NO_LABELS = LabelSpec(enabled=False)


def test_shank_radius_round_and_hex():
    specs = Specs(socket=SocketSpec(hex_size=6.35))
    assert shank_radius(Drill(6.0, 60, ShankType.ROUND), specs) == pytest.approx(3.0)
    # Hex: радиус по стандартному размеру «под ключ» (hex_size), диаметр сверла НЕ влияет.
    assert shank_radius(Drill(6.0, 60, ShankType.HEX), specs) == pytest.approx(6.35 / math.sqrt(3))
    assert shank_radius(Drill(99.0, 60, ShankType.HEX), specs) == pytest.approx(6.35 / math.sqrt(3))


def test_bore_radius_adds_clearance():
    specs = Specs(socket=SocketSpec(clearance=0.2, hex_clearance=0.3, hex_size=6.35))
    assert bore_radius(Drill(6.0, 60, ShankType.ROUND), specs) == pytest.approx(3.2)
    # Hex-гнездо считается от hex_size, а не от диаметра сверла.
    assert bore_radius(Drill(6.0, 60, ShankType.HEX), specs) == pytest.approx(6.35 / math.sqrt(3) + 0.3)


def test_outer_radius_with_and_without_springs():
    drill = Drill(6.0, 60, ShankType.ROUND)
    socket = SocketSpec(clearance=0.15)
    with_s = Specs(socket=socket, springs=SpringSpec(enabled=True, leaf_thickness=1.2, relief_gap=0.8))
    without = Specs(socket=socket, springs=SpringSpec(enabled=False))
    # bore = 3.0 + clearance 0.15; + leaf_thickness + relief_gap
    assert socket_outer_radius(drill, with_s) == pytest.approx(3.15 + 1.2 + 0.8)
    assert socket_outer_radius(drill, without) == pytest.approx(3.15)


def test_hex_outer_radius_with_springs():
    # Hex-гнёзда тоже имеют детенты (осевая фиксация): внешний радиус учитывает нишу за гранью.
    hexd = Drill(5.0, 60, ShankType.HEX)
    socket = SocketSpec(hex_clearance=0.2, hex_size=6.35)
    with_s = Specs(socket=socket, springs=SpringSpec(enabled=True, leaf_thickness=1.2, relief_gap=0.8))
    without = Specs(socket=socket, springs=SpringSpec(enabled=False))
    rc = 6.35 / math.sqrt(3) + 0.2                  # описанный радиус
    apothem = rc * math.sqrt(3) / 2.0
    assert socket_outer_radius(hexd, with_s) == pytest.approx(max(rc, apothem + 1.2 + 0.8))
    # Без пружин — само посадочное отверстие (описанный радиус).
    assert socket_outer_radius(hexd, without) == pytest.approx(rc)


def test_resolve_depth_clamped():
    specs = Specs(socket=SocketSpec(depth_ratio=0.4, min_depth=8, max_depth=30))
    assert resolve_depth(Drill(3, 10, ShankType.ROUND), specs) == 8     # 4.0 → min
    assert resolve_depth(Drill(3, 50, ShankType.ROUND), specs) == 20    # 20.0 в диапазоне
    assert resolve_depth(Drill(3, 100, ShankType.ROUND), specs) == 30   # 40.0 → max


def test_recommend_mode_heuristic():
    short_few = [Drill(3, 50, ShankType.ROUND) for _ in range(5)]
    short_many = [Drill(3, 50, ShankType.ROUND) for _ in range(12)]
    has_long = [Drill(3, 50, ShankType.ROUND), Drill(8, 130, ShankType.ROUND)]
    assert recommend_mode(short_few) is LayoutMode.ROW
    assert recommend_mode(short_many) is LayoutMode.GRID
    assert recommend_mode(has_long) is LayoutMode.ANGLED


def test_row_positions_non_overlapping_and_sorted():
    drills = [Drill(6, 60, ShankType.ROUND), Drill(3, 60, ShankType.ROUND), Drill(4, 60, ShankType.ROUND)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.ROW, pitch_extra=4))
    plan = resolve_plan(drills, specs)
    # Отсортировано по диаметру.
    assert [s.drill.d for s in plan.sockets] == [3, 4, 6]
    # Соседи не пересекаются: расстояние >= сумма радиусов.
    for a, b in zip(plan.sockets, plan.sockets[1:]):
        gap = b.x - a.x
        assert gap >= a.outer_radius + b.outer_radius - 1e-9


def test_row_sorted_by_real_socket_size_not_drill_diameter():
    # Гнездо «5 hex» (под ключ 6.35) больше гнезда «6 round» → должно стоять ПОЗЖЕ в ряду,
    # хотя диаметр сверла у него меньше. Сортировка идёт по реальному размеру гнезда.
    hex5 = Drill(5.0, 60, ShankType.HEX)
    round6 = Drill(6.0, 60, ShankType.ROUND)
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.ROW))
    plan = resolve_plan([hex5, round6], specs)
    order = [(s.drill.d, s.drill.shank) for s in plan.sockets]
    assert order == [(6.0, ShankType.ROUND), (5.0, ShankType.HEX)]
    # И позиции монотонны по внешнему радиусу.
    assert plan.sockets[0].outer_radius <= plan.sockets[1].outer_radius


def test_row_align_center_keeps_axis():
    # По умолчанию (center) все гнёзда стоят на оси ряда — y == 0.
    drills = [Drill(6, 60, ShankType.ROUND), Drill(3, 60, ShankType.ROUND)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.ROW, align=RowAlign.CENTER))
    plan = resolve_plan(drills, specs)
    assert all(s.y == pytest.approx(0.0) for s in plan.sockets)


def test_row_align_front_lines_up_near_edges():
    # FRONT: ближние кромки (y - r) всех гнёзд на одной линии = −r_max; крупнейшее остаётся на оси.
    drills = [Drill(6, 60, ShankType.ROUND), Drill(3, 60, ShankType.ROUND)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.ROW, align=RowAlign.FRONT))
    plan = resolve_plan(drills, specs)
    front_edges = [s.y - s.outer_radius for s in plan.sockets]
    r_max = max(s.outer_radius for s in plan.sockets)
    assert all(e == pytest.approx(-r_max) for e in front_edges)
    biggest = max(plan.sockets, key=lambda s: s.outer_radius)
    assert biggest.y == pytest.approx(0.0)


def test_row_align_back_lines_up_far_edges():
    # BACK: дальние кромки (y + r) всех гнёзд на одной линии = +r_max; крупнейшее остаётся на оси.
    drills = [Drill(6, 60, ShankType.ROUND), Drill(3, 60, ShankType.ROUND)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.ROW, align=RowAlign.BACK))
    plan = resolve_plan(drills, specs)
    back_edges = [s.y + s.outer_radius for s in plan.sockets]
    r_max = max(s.outer_radius for s in plan.sockets)
    assert all(e == pytest.approx(r_max) for e in back_edges)
    biggest = max(plan.sockets, key=lambda s: s.outer_radius)
    assert biggest.y == pytest.approx(0.0)


def test_grid_splits_into_expected_rows():
    # 9 свёрел, авто-столбцы = ceil(sqrt(9)) = 3 → 3 ряда. При align=center каждый ряд лежит на
    # своей оси Y, поэтому уникальных Y = число рядов.
    drills = [Drill(float(i), 60, ShankType.ROUND) for i in range(2, 11)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.GRID))  # align=center по умолчанию
    plan = resolve_plan(drills, specs)
    rows = sorted(set(round(s.y, 6) for s in plan.sockets))
    assert len(rows) == 3


def _grid_rows_by_y(plan):
    """Сгруппировать гнёзда плана по рядам (по округлённому Y), ряды по возрастанию Y."""
    rows = {}
    for s in plan.sockets:
        rows.setdefault(round(s.y, 6), []).append(s)
    return [rows[y] for y in sorted(rows)]


def test_grid_rows_share_common_center_x():
    # space-around: ряды центрированы по одной вертикальной оси (а не выровнены по левому краю).
    drills = [Drill(float(i), 60, ShankType.ROUND) for i in range(2, 11)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.GRID, grid_cols=3), labels=_NO_LABELS)
    plan = resolve_plan(drills, specs)
    centers = []
    for row in _grid_rows_by_y(plan):
        left = min(s.x - s.outer_radius for s in row)
        right = max(s.x + s.outer_radius for s in row)
        centers.append((left + right) / 2.0)
    assert all(c == pytest.approx(centers[0]) for c in centers)


def test_grid_space_around_equal_gaps_and_half_edges():
    # Один ряд (cols = всё): внутренние зазоры равны, краевой отступ = половине внутреннего.
    sizes = [2.0, 5.0, 8.0, 3.0, 6.0]
    drills = [Drill(d, 60, ShankType.ROUND) for d in sizes]
    pitch = 4.0
    specs = Specs(
        layout=LayoutSpec(mode=LayoutMode.GRID, grid_cols=len(sizes), pitch_extra=pitch),
        labels=_NO_LABELS,
    )
    plan = resolve_plan(drills, specs)
    row = sorted(plan.sockets, key=lambda s: s.x)
    gaps = [(b.x - b.outer_radius) - (a.x + a.outer_radius) for a, b in zip(row, row[1:])]
    assert all(g == pytest.approx(gaps[0]) for g in gaps)
    # space-around: gap = (n-1)*pitch/n; краевой отступ = gap/2.
    n = len(sizes)
    assert gaps[0] == pytest.approx((n - 1) * pitch / n)
    lead = min(s.x - s.outer_radius for s in row)
    assert lead == pytest.approx(gaps[0] / 2.0)


def test_grid_no_horizontal_overlap_within_row():
    drills = [Drill(float(i), 60, ShankType.ROUND) for i in range(2, 11)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.GRID, grid_cols=3, pitch_extra=2.0))
    plan = resolve_plan(drills, specs)
    for y in set(round(s.y, 6) for s in plan.sockets):
        row = sorted((s for s in plan.sockets if round(s.y, 6) == y), key=lambda s: s.x)
        for a, b in zip(row, row[1:]):
            assert b.x - a.x >= a.outer_radius + b.outer_radius - 1e-9


def test_grid_rows_do_not_overlap_vertically():
    # Полосы соседних рядов не пересекаются: задняя кромка ряда ≤ передней кромки следующего.
    drills = [Drill(float(i), 60, ShankType.ROUND) for i in range(2, 11)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.GRID, grid_cols=3))
    plan = resolve_plan(drills, specs)
    ys = sorted(set(round(s.y, 6) for s in plan.sockets))
    bands = []
    for y in ys:
        row = [s for s in plan.sockets if round(s.y, 6) == y]
        bands.append((min(s.y - s.outer_radius for s in row), max(s.y + s.outer_radius for s in row)))
    for (_, back), (front, _) in zip(bands, bands[1:]):
        assert front >= back - 1e-9


def test_grid_align_front_lines_up_rows_front_edges():
    # align работает и в сетке: при FRONT передние кромки (y − r) всех гнёзд одного ряда лежат на
    # одной линии (мелкие гнёзда сдвинуты вперёд к кромке крупнейшего). Свёрла отсортированы по
    # возрастанию, заполнение по рядам — поэтому ряд = срез по cols в этом порядке.
    cols = 3
    drills = [Drill(float(i), 60, ShankType.ROUND) for i in range(2, 11)]
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.GRID, grid_cols=cols, align=RowAlign.FRONT))
    plan = resolve_plan(drills, specs)
    sockets = plan.sockets  # уже в порядке раскладки (отсортированы по размеру гнезда)
    for start in range(0, len(sockets), cols):
        row = sockets[start : start + cols]
        front_edges = [s.y - s.outer_radius for s in row]
        assert max(front_edges) - min(front_edges) == pytest.approx(0.0)


def test_auto_mode_resolved_in_plan():
    drills = [Drill(3, 50, ShankType.ROUND) for _ in range(4)]
    plan = resolve_plan(drills, Specs(layout=LayoutSpec(mode=LayoutMode.AUTO)))
    assert plan.resolved_mode is LayoutMode.ROW  # auto уже разрешён


# ── Учёт места под подписи в раскладке ──────────────────────────────────────────

def test_socket_extents_label_front_extends_beyond_radius():
    drill = Drill(3.0, 60, ShankType.ROUND)
    labels = LabelSpec(enabled=True, position=LabelPosition.FRONT, size=4.0, offset=5.0)
    specs = Specs(layout=LayoutSpec(), labels=labels)
    ext = socket_extents(drill, specs)
    r = socket_outer_radius(drill, specs)
    assert ext["front"] > r            # подпись выносится вперёд за гнездо
    assert ext["back"] == pytest.approx(r)   # назад — только гнездо
    # Поперёк (по X) текст центрирован и может торчать вбок.
    assert ext["left"] >= r and ext["right"] >= r


def test_socket_extents_no_labels_is_just_radius():
    drill = Drill(3.0, 60, ShankType.ROUND)
    specs = Specs(layout=LayoutSpec(), labels=_NO_LABELS)
    r = socket_outer_radius(drill, specs)
    assert socket_extents(drill, specs) == {"front": r, "back": r, "left": r, "right": r}


def test_grid_labels_reserve_vertical_space_between_rows():
    # С подписями (вынос вперёд) ряды должны расходиться сильнее, чем без них.
    drills = [Drill(float(i), 60, ShankType.ROUND) for i in range(1, 10)]
    base = LayoutSpec(mode=LayoutMode.GRID, grid_cols=3)
    labels = LabelSpec(enabled=True, position=LabelPosition.FRONT, size=4.0, offset=5.0)
    with_labels = resolve_plan(drills, Specs(layout=base, labels=labels))
    without = resolve_plan(drills, Specs(layout=base, labels=_NO_LABELS))

    def y_span(plan):
        ys = [s.y for s in plan.sockets]
        return max(ys) - min(ys)

    assert y_span(with_labels) > y_span(without)


def test_grid_label_boxes_do_not_overlap():
    # Главная проверка: рамки «гнездо + подпись» не пересекаются ни у одной пары (ни между рядами,
    # ни внутри ряда) — то, что было сломано на рендере.
    drills = [Drill(d, 60, ShankType.ROUND) for d in
              [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10]]
    labels = LabelSpec(enabled=True, position=LabelPosition.FRONT, size=4.0, offset=5.0)
    specs = Specs(layout=LayoutSpec(mode=LayoutMode.GRID, pitch_extra=4.0), labels=labels)
    plan = resolve_plan(drills, specs)
    boxes = []
    for s in plan.sockets:
        e = socket_extents(s.drill, specs)
        boxes.append((s.x - e["left"], s.x + e["right"], s.y - e["front"], s.y + e["back"])),
    eps = 1e-6
    for i in range(len(boxes)):
        x0, x1, y0, y1 = boxes[i]
        for j in range(i + 1, len(boxes)):
            X0, X1, Y0, Y1 = boxes[j]
            overlap_x = min(x1, X1) - max(x0, X0)
            overlap_y = min(y1, Y1) - max(y0, Y0)
            assert overlap_x <= eps or overlap_y <= eps, f"пересечение рамок {i} и {j}"
