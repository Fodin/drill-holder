"""Подписи: текст → 3D-выдавливание, ориентированное по рабочей грани.

Текст строится через Draft ShapeString (нужен TTF-шрифт). Если шрифт не задан/не найден или
построение не удалось — подпись пропускается с предупреждением, сборка не падает.

Два режима (``LabelSpec.mode``): ``engrave`` — тело текста уходит вглубь грани, вызывающая
сторона его вычитает; ``emboss`` — тело торчит наружу рельефом и приваривается. Сама форма
строится здесь одинаково, разница — в знаке выноса по нормали (см. ниже), а cut/fuse решает
``assembly``.
"""

from __future__ import annotations

import FreeCAD as App

from ..model import LabelMode, LabelPosition, LabelReference, LabelSpec, Socket

_Z = App.Vector(0, 0, 1)
_ORIGIN = App.Vector(0, 0, 0)

# Насколько выпуклый (emboss) текст утоплен внутрь тела: гарантирует пересечение объёмов, иначе
# у fuse совпадающие грани дают шов/невалидную форму. На результат печати не влияет (внутри тела).
_EMBOSS_EMBED = 0.4


def _offset_dir(position: LabelPosition, surface) -> App.Vector:
    """Направление выноса подписи от центра гнезда в базисе рабочей грани.

    Используем оператор ``*`` (возвращает новый вектор) — метод ``Vector.multiply`` в FreeCAD
    мутирует на месте и испортил бы общие базисные векторы поверхности.
    """
    if position is LabelPosition.FRONT:
        return surface.v * -1.0
    if position is LabelPosition.BACK:
        return surface.v * 1.0
    if position is LabelPosition.LEFT:
        return surface.u * -1.0
    return surface.u * 1.0  # RIGHT


def make_label(doc, socket: Socket, surface, spec: LabelSpec, font: str):
    """Вернуть выдавленный текст подписи (``Part.Shape``) или ``None`` при неудаче.

    Форма ориентирована так, что вызывающая сторона для ``engrave`` её вычитает, для ``emboss`` —
    приваривает. ``font`` — уже разрешённый путь к шрифту (подбор и предупреждение делает
    вызывающая сторона один раз). ``doc`` нужен Draft ShapeString для временного объекта (он
    тут же удаляется).
    """
    text = socket.drill.label.strip() or _format_diameter(socket.drill.d)
    try:
        import Draft

        ss = Draft.make_shapestring(String=text, FontFile=font, Size=spec.size)
        doc.recompute()
        shape = ss.Shape.copy()
        doc.removeObject(ss.Name)
    except Exception as exc:  # noqa: BLE001 — любая ошибка шрифта/Draft → graceful skip
        App.Console.PrintWarning(f"[labels] не удалось построить '{text}': {exc}\n")
        return None

    if shape is None or shape.isNull() or not shape.Faces:
        App.Console.PrintWarning(f"[labels] пустой контур для '{text}' — пропуск\n")
        return None

    # Центрируем текст в плоскости XY, затем выдавливаем по +Z. Для emboss тянем чуть глубже на
    # _EMBOSS_EMBED — этот «корень» уйдёт внутрь тела и обеспечит надёжное объединение.
    bb = shape.BoundBox
    shape.translate(App.Vector(-(bb.XMin + bb.XLength / 2.0), -(bb.YMin + bb.YLength / 2.0), 0))
    embed = _EMBOSS_EMBED if spec.mode is LabelMode.EMBOSS else 0.0
    text3d = shape.extrude(App.Vector(0, 0, spec.depth + embed))

    # Полугабарит текста вдоль оси выноса: для FRONT/BACK вынос по v → половина высоты,
    # для LEFT/RIGHT по u → половина ширины. offset — зазор до ближней кромки, не до центра.
    if spec.position in (LabelPosition.FRONT, LabelPosition.BACK):
        half = bb.YLength / 2.0
    else:
        half = bb.XLength / 2.0

    # Подпись всегда выносится от своего отверстия (работает и для ряда, и для сетки). Точка
    # привязки: EDGE — край гнезда (стабильный зазор offset от кромки при любом размере), CENTER —
    # центр гнезда (фиксированное расстояние от центра → подписи выстраиваются ровно в сетке).
    # offset — зазор до БЛИЖНЕЙ кромки текста, поэтому добавляем half (полугабарит вдоль выноса).
    # Операторы +/-/* возвращают новые векторы (методы add/sub/multiply мутируют на месте).
    anchor = socket.outer_radius if spec.reference is LabelReference.EDGE else 0.0
    dist = anchor + spec.offset + half
    target = surface.point(socket.x, socket.y) + _offset_dir(spec.position, surface) * dist
    # Локальная z=0 ложится в точку base, ось +z идёт по нормали грани наружу. Для engrave опускаем
    # base на depth внутрь — тело текста под гранью, верх заподлицо. Для emboss опускаем лишь на
    # embed (корень внутри тела), верх торчит наружу на depth → рельеф.
    sink = spec.depth if spec.mode is LabelMode.ENGRAVE else embed
    base = target - surface.normal * sink
    text3d.Placement = App.Placement(base, surface.rotation)
    return text3d


def _format_diameter(d: float) -> str:
    """'3.0' для целых десятых, иначе обрезаем хвостовые нули ('6.35')."""
    return f"{d:.2f}".rstrip("0").rstrip(".")
