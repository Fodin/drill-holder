"""Стартовый ракурс камеры для .FCStd — адаптер к FreeCAD.

Headless-сборка (`freecadcmd`) НЕ пишет ``GuiDocument.xml``, поэтому FreeCAD открывает
модель в дефолтном ракурсе и масштабе. Здесь мы собираем минимальный ``GuiDocument.xml`` с
ортографической камерой, вписанной в габарит всей сборки под изометрией, и внедряем его в
FCStd-zip после сохранения.

Поведение при пересборке (как просил пользователь):
  * если в ПРЕЖНЕМ файле была камера (например, пользователь повернул вид и сохранил во FreeCAD) —
    переиспользуем её ОРИЕНТАЦИЮ (тот же ракурс), но позицию и высоту пересчитываем под новый
    габарит. Ракурс сохраняется, масштаб всегда корректный — модель не уезжает за экран;
  * если прежней камеры нет — ставим пресет-изометрию (вид со стороны +X,−Y,+Z, как
    View → Isometric во FreeCAD), вписанную в габарит.

Модуль трогает FreeCAD только через :mod:`FreeCAD` (App: ``Vector``/``Rotation``/``BoundBox``),
GUI не нужен — works in ``freecadcmd``.
"""

from __future__ import annotations

import re
import zipfile
from typing import List, Optional, Tuple

import FreeCAD as App
from FreeCAD import Vector

_GUI_DOC = "GuiDocument.xml"
_FIT_MARGIN = 1.05  # запас, чтобы габарит не упирался в края кадра
# Метка нашего авто-пресета в GuiDocument.xml. Позволяет отличить «камеру, которую вписали мы»
# от «вида, который пользователь повернул и сохранил во FreeCAD»: наш пресет при пересборке
# обновляем из кода (правки направления распространяются), пользовательский ракурс — сохраняем.
_AUTO_MARK = "drillholder:auto-camera"

# Кортеж камеры: (axis_x, axis_y, axis_z, angle) — ориентация в формате ось-угол (как у Inventor).
AxisAngle = Tuple[float, float, float, float]


# Детали, скрытые в стартовом виде (видимость false). Крышка обычно загораживает корпус и
# гнёзда — по умолчанию её не показываем; вписывание кадра тоже идёт без неё.
_HIDDEN_BY_DEFAULT = frozenset({"Lid"})


def _combined_bbox(parts: List[Tuple[str, object]]):
    """Объединённый BoundBox по ВИДИМЫМ деталям (или ``None``, если форм нет).

    Скрытые по умолчанию детали (:data:`_HIDDEN_BY_DEFAULT`, напр. крышка) в кадр не вписываем —
    иначе высокая крышка над корпусом раздула бы габарит и уменьшила корпус.
    """
    bb = None
    for name, feature in parts:
        if name in _HIDDEN_BY_DEFAULT:
            continue
        shape = getattr(feature, "Shape", None)
        if shape is None:
            continue
        b = shape.BoundBox
        bb = b if bb is None else bb.united(b)
    return bb


def _isometric_axis_angle() -> AxisAngle:
    """Ориентация камеры для изометрии: наблюдатель со стороны (−X, −Y, +Z) — снизу-слева спереди."""
    z = Vector(-1, -1, 1)  # локальный +Z камеры смотрит НА наблюдателя
    z.normalize()
    x = Vector(0, 0, 1).cross(z)  # правый вектор (из мировой вертикали)
    x.normalize()
    y = z.cross(x)  # вектор «вверх» экрана
    y.normalize()
    rot = App.Rotation(x, y, z)
    ax = rot.Axis
    return (ax.x, ax.y, ax.z, rot.Angle)


def _fit_camera_settings(bbox, axis_angle: AxisAngle) -> str:
    """Собрать Inventor-строку OrthographicCamera, вписанную в ``bbox`` при данной ориентации.

    Позиция и высота считаются из габарита, поэтому при любой ориентации сцена влезает в кадр
    с запасом :data:`_FIT_MARGIN`. Камера смотрит вдоль своего −Z (стандарт SoCamera).
    """
    ax, ay, az, ang = axis_angle
    # App.Rotation(axis, angle) ждёт угол в ГРАДУСАХ — переводим из радиан (ang).
    rot = App.Rotation(Vector(ax, ay, az), ang * 180.0 / 3.141592653589793)
    z_local = rot.multVec(Vector(0, 0, 1))  # направление НА наблюдателя
    center = bbox.Center
    radius = 0.5 * bbox.DiagonalLength
    dist = 2.0 * radius if radius > 1e-9 else 10.0
    pos = center + z_local.multiply(dist)  # камера со стороны +z_local (viewdir = −z_local смотрит в сцену)
    height = bbox.DiagonalLength * _FIT_MARGIN
    near = max(0.01, dist - radius)
    far = dist + radius
    focal = dist
    return (
        "#Inventor V2.1 ascii\n\n\n"
        "OrthographicCamera {\n"
        "  viewportMapping ADJUST_CAMERA\n"
        f"  position {pos.x:.6f} {pos.y:.6f} {pos.z:.6f}\n"
        f"  orientation {ax:.7f} {ay:.7f} {az:.7f}  {ang:.7f}\n"
        f"  nearDistance {near:.6f}\n"
        f"  farDistance {far:.6f}\n"
        "  aspectRatio 1\n"
        f"  focalDistance {focal:.6f}\n"
        f"  height {height:.6f}\n"
        "}\n"
    )


def _extract_axis_angle(gui_xml: str) -> Optional[AxisAngle]:
    """Вытащить ориентацию (ось-угол) из ``orientation`` прежней камеры, либо ``None``."""
    m = re.search(
        r"orientation\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)",
        gui_xml,
    )
    if not m:
        return None
    try:
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
    except ValueError:
        return None


def _attr_escape(text: str) -> str:
    """Экранировать строку под значение XML-атрибута (включая перевод строки как ``&#10;``)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "&#10;")
    )


def build_gui_document_xml(parts: List[Tuple[str, object]], prev_xml: Optional[str] = None) -> Optional[str]:
    """Собрать текст ``GuiDocument.xml`` с камерой стартового ракурса.

    Если ``prev_xml`` содержит ориентацию прежней камеры — берём её ракурс (а позицию/высоту
    пересчитываем под текущий габарит). Иначе ставим пресет-изометрию. Возвращает ``None``,
    если у деталей нет геометрии (вписывать не во что).
    """
    bbox = _combined_bbox(parts)
    if bbox is None:
        return None
    # Реюз ракурса — ТОЛЬКО если прежняя камера пользовательская (без нашей метки). Свой пресет
    # при пересборке берём из кода, чтобы правки направления/масштаба распространялись.
    reuse = bool(prev_xml) and _AUTO_MARK not in prev_xml
    axis_angle = (_extract_axis_angle(prev_xml) if reuse else None) or _isometric_axis_angle()
    settings = _attr_escape(_fit_camera_settings(bbox, axis_angle))

    providers = "\n".join(
        f'        <ViewProvider name="{name}" expanded="0">\n'
        f'            <Properties Count="1" TransientCount="0">\n'
        f'                <Property name="Visibility" type="App::PropertyBool" status="1">\n'
        f'                    <Bool value="{"false" if name in _HIDDEN_BY_DEFAULT else "true"}"/>\n'
        f"                </Property>\n"
        f"            </Properties>\n"
        f"        </ViewProvider>"
        for name, _feature in parts
    )
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {_AUTO_MARK} -->\n"
        "<!--\n FreeCAD Document, see https://www.freecad.org for more information...\n-->\n"
        '<Document SchemaVersion="1">\n'
        f'    <ViewProviderData Count="{len(parts)}">\n'
        f"{providers}\n"
        "    </ViewProviderData>\n"
        f'    <Camera settings="{settings}"/>\n'
        "</Document>\n"
    )


def read_gui_document_xml(fcstd_path: str) -> Optional[str]:
    """Прочитать ``GuiDocument.xml`` из существующего FCStd (для переиспользования камеры)."""
    try:
        with zipfile.ZipFile(fcstd_path) as zf:
            if _GUI_DOC in zf.namelist():
                return zf.read(_GUI_DOC).decode("utf-8")
    except (FileNotFoundError, zipfile.BadZipFile, KeyError):
        pass
    return None


def inject_camera(fcstd_path: str, parts: List[Tuple[str, object]], prev_xml: Optional[str]) -> str:
    """Дописать в FCStd-zip ``GuiDocument.xml`` со стартовой камерой.

    Возвращает режим для лога: ``"reused"`` (сохранён пользовательский ракурс), ``"preset"``
    (пресет-изометрия) или ``""`` (не записали — нет геометрии/проблема с zip; не falsy-ошибка,
    а штатный откат: модель просто откроется в дефолтном виде).
    """
    xml = build_gui_document_xml(parts, prev_xml)
    if xml is None:
        return ""
    try:
        with zipfile.ZipFile(fcstd_path, "a", zipfile.ZIP_DEFLATED) as zf:
            existing = set(zf.namelist())
        if _GUI_DOC in existing:
            return ""  # FreeCAD уже записал свой GUI-слой — не трогаем
        with zipfile.ZipFile(fcstd_path, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_GUI_DOC, xml)
        return "reused" if (prev_xml and _AUTO_MARK not in prev_xml) else "preset"
    except (FileNotFoundError, zipfile.BadZipFile):
        return ""
