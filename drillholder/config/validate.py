"""Валидация слитого конфига и сборка типизированных Value Objects из :mod:`drillholder.model`.

Принимает уже слитый поверх :data:`DEFAULTS` словарь (см. :mod:`drillholder.config.loader`)
и строит ``(drills, Specs)``. Невалидные значения → :class:`ConfigError` с понятным сообщением.

Конвенция (см. CLAUDE.md): для подбираемых величин (число/ряды пружин) мягко авто-уменьшаем
до влезающего значения и пишем WARNING, а не падаем. ``ConfigError`` — только для принципиально
невозможного. Диагностику шлём в лог; FreeCAD-слой/CLI направляет WARNING в жёлтую консоль.
Чистый слой сам ничего не печатает.

Модуль чистый: FreeCAD не нужен.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..lengths import standard_length
from ..model import (
    BaseSpec,
    Drill,
    DrillGeometrySpec,
    DrillStyle,
    FootMode,
    FootSpec,
    LabelMode,
    LabelPosition,
    LabelReference,
    LabelSpec,
    LayoutMode,
    LayoutSpec,
    LidMode,
    LidSpec,
    OutputSpec,
    RingSpec,
    RowAlign,
    ShankType,
    SocketSpec,
    SpringSpec,
    Specs,
)
from .errors import ConfigError
from .loader import load_raw_config

_log = logging.getLogger("drillholder")


def _require_positive(value: float, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name}: ожидается число, получено {value!r}")
    if v <= 0:
        raise ConfigError(f"{name}: должно быть > 0, получено {v}")
    return v


def _build_drills(raw_drills: Any, socket: SocketSpec, default_shank: str) -> List[Drill]:
    if not isinstance(raw_drills, list) or not raw_drills:
        raise ConfigError("drills: должен быть непустым списком свёрел")

    drills: List[Drill] = []
    for i, item in enumerate(raw_drills):
        if not isinstance(item, dict):
            raise ConfigError(f"drills[{i}]: ожидается словарь, получено {item!r}")
        d = _require_positive(item.get("d"), f"drills[{i}].d")

        # Тип хвостовика берётся из сверла, иначе — общий дефолт из конфига.
        raw_shank = str(item.get("shank", default_shank)).lower()
        try:
            shank = ShankType(raw_shank)
        except ValueError:
            raise ConfigError(
                f"drills[{i}].shank: ожидается 'round' или 'hex', получено {raw_shank!r}"
            )

        # length опциональна: отсутствует или "auto" → стандартная длина по диаметру (DIN 338).
        length_raw = item.get("length")
        if length_raw is None or (isinstance(length_raw, str) and length_raw.strip().lower() == "auto"):
            length = standard_length(d)
        else:
            length = _require_positive(length_raw, f"drills[{i}].length")

        label = str(item.get("label", "")).strip()
        drills.append(Drill(d=d, length=length, shank=shank, label=label))
    return drills


def _build_socket(raw: Dict[str, Any]) -> SocketSpec:
    s = SocketSpec(
        clearance=float(raw["clearance"]),
        depth_ratio=_require_positive(raw["depth_ratio"], "socket.depth_ratio"),
        min_depth=_require_positive(raw["min_depth"], "socket.min_depth"),
        max_depth=_require_positive(raw["max_depth"], "socket.max_depth"),
        hex_size=_require_positive(raw["hex_size"], "socket.hex_size"),
        hex_clearance=float(raw["hex_clearance"]),
        hex_flat_up=bool(raw["hex_flat_up"]),
    )
    if s.max_depth < s.min_depth:
        raise ConfigError(
            f"socket.max_depth ({s.max_depth}) должно быть >= socket.min_depth ({s.min_depth})"
        )
    return s


def _build_springs(raw: Dict[str, Any]) -> SpringSpec:
    s = SpringSpec(
        enabled=bool(raw["enabled"]),
        count=int(raw["count"]),
        rows=int(raw["rows"]),
        leaf_width=float(raw["leaf_width"]),
        leaf_length=float(raw["leaf_length"]),
        leaf_thickness=float(raw["leaf_thickness"]),
        slot_width=float(raw["slot_width"]),
        relief_gap=float(raw["relief_gap"]),
        bump_protrusion=float(raw["bump_protrusion"]),
        bump_radius=float(raw["bump_radius"]),
    )
    if s.enabled:
        if s.count < 1:
            raise ConfigError(f"springs.count: нужно >= 1 лепестка, получено {s.count}")
        if s.rows < 1:
            raise ConfigError(f"springs.rows: нужно >= 1 ряда, получено {s.rows}")
        for name in ("leaf_width", "leaf_length", "leaf_thickness", "slot_width", "relief_gap"):
            _require_positive(getattr(s, name), f"springs.{name}")
        _require_positive(s.bump_radius, "springs.bump_radius")
        if s.bump_protrusion <= 0:
            raise ConfigError(f"springs.bump_protrusion: должно быть > 0, получено {s.bump_protrusion}")
        # Детент должен бондиться с лепестком (внешняя кромка валика доходит до стенки гнезда).
        if s.bump_radius < s.bump_protrusion / 2.0:
            raise ConfigError(
                f"springs.bump_radius ({s.bump_radius}) должно быть >= bump_protrusion/2 "
                f"({s.bump_protrusion / 2.0}), иначе детент не приваривается к лепестку."
            )
    return s


def _build_layout(raw: Dict[str, Any]) -> LayoutSpec:
    raw_mode = str(raw["mode"]).lower()
    try:
        mode = LayoutMode(raw_mode)
    except ValueError:
        valid = ", ".join(m.value for m in LayoutMode)
        raise ConfigError(f"layout.mode: ожидается одно из [{valid}], получено {raw_mode!r}")
    angle = float(raw["angle_deg"])
    if mode is LayoutMode.ANGLED and not 0 < angle < 90:
        raise ConfigError(f"layout.angle_deg: для angled нужно в (0, 90), получено {angle}")
    raw_align = str(raw["align"]).lower()
    try:
        align = RowAlign(raw_align)
    except ValueError:
        valid = ", ".join(a.value for a in RowAlign)
        raise ConfigError(f"layout.align: ожидается одно из [{valid}], получено {raw_align!r}")
    return LayoutSpec(
        mode=mode,
        grid_cols=int(raw["grid_cols"]),
        serpentine=bool(raw["serpentine"]),
        angle_deg=angle,
        pitch_extra=float(raw["pitch_extra"]),
        edge_margin=float(raw["edge_margin"]),
        row_gap=float(raw["row_gap"]),
        align=align,
    )


def _build_labels(raw: Dict[str, Any]) -> LabelSpec:
    raw_mode = str(raw["mode"]).lower()
    try:
        mode = LabelMode(raw_mode)
    except ValueError:
        valid = ", ".join(m.value for m in LabelMode)
        raise ConfigError(f"labels.mode: ожидается одно из [{valid}], получено {raw_mode!r}")
    raw_pos = str(raw["position"]).lower()
    try:
        position = LabelPosition(raw_pos)
    except ValueError:
        valid = ", ".join(p.value for p in LabelPosition)
        raise ConfigError(f"labels.position: ожидается одно из [{valid}], получено {raw_pos!r}")
    raw_ref = str(raw["reference"]).lower()
    try:
        reference = LabelReference(raw_ref)
    except ValueError:
        valid = ", ".join(r.value for r in LabelReference)
        raise ConfigError(f"labels.reference: ожидается одно из [{valid}], получено {raw_ref!r}")
    return LabelSpec(
        enabled=bool(raw["enabled"]),
        mode=mode,
        position=position,
        reference=reference,
        size=float(raw["size"]),
        depth=float(raw["depth"]),
        font=str(raw["font"]),
        offset=float(raw["offset"]),
        multicolor=bool(raw["multicolor"]),
    )


def _build_rings(raw: Dict[str, Any]) -> RingSpec:
    enabled = bool(raw["enabled"])
    width = float(raw["width"])
    if enabled and width <= 0:
        raise ConfigError(f"rings.width: ширина колечка должна быть > 0, получено {width:g}")
    return RingSpec(
        enabled=enabled,
        width=width,
        depth=float(raw["depth"]),
        gap=float(raw["gap"]),
    )


def _build_output(raw: Dict[str, Any]) -> OutputSpec:
    formats = tuple(str(x).upper() for x in raw["formats"])
    known = {"FCSTD", "STL", "STEP"}
    unknown = [f for f in formats if f not in known]
    if unknown:
        raise ConfigError(f"output.formats: неизвестные форматы {unknown}; допустимы FCStd/STL/STEP")
    # Нормализуем регистр к каноническому виду, ожидаемому экспортёром.
    canon = {"FCSTD": "FCStd", "STL": "STL", "STEP": "STEP"}
    return OutputSpec(
        directory=str(raw["dir"]),
        name=str(raw["name"]),
        formats=tuple(canon[f] for f in formats),
        linear_deflection=float(raw["linear_deflection"]),
        angular_deflection=float(raw["angular_deflection"]),
    )


def build_specs(merged: Dict[str, Any]) -> Tuple[List[Drill], Specs]:
    """Провалидировать слитый конфиг и собрать типизированные объекты.

    Возвращает ``(drills, specs)``. Бросает :class:`ConfigError` с понятным сообщением.
    """
    socket = _build_socket(merged["socket"])
    springs = _build_springs(merged["springs"])
    drills = _build_drills(merged["drills"], socket, str(merged["default_shank"]).lower())

    # Зажим детента (от диаметра не зависит) — единственная принципиально невозможная вещь, проверяем
    # рано и жёстко. Подгонка count/rows/ширины лепестка — ПЕР-ГНЕЗДОВАЯ (layout.fit_springs на этапе
    # геометрии): каждое гнездо берёт по максимуму влезающего, мелкое сверло не урезает крупные.
    if springs.enabled:
        _validate_spring_grip(drills, springs, socket)

    layout = _build_layout(merged["layout"])
    lid = _build_lid(merged["lid"])
    if lid.mode is not LidMode.NONE and layout.mode is LayoutMode.ANGLED:
        raise ConfigError("lid: крышка поддерживается только для прямых раскладок, не для angled")

    specs = Specs(
        socket=socket,
        springs=springs,
        layout=layout,
        base=_build_base(merged["base"]),
        labels=_build_labels(merged["labels"]),
        rings=_build_rings(merged["rings"]),
        lid=lid,
        foot=_build_foot(merged["foot"]),
        drill_geometry=_build_drill_geometry(merged["drill_geometry"]),
        output=_build_output(merged["output"]),
    )
    return drills, specs


def _build_lid(raw: Dict[str, Any]) -> LidSpec:
    raw_mode = str(raw["mode"]).lower()
    try:
        mode = LidMode(raw_mode)
    except ValueError:
        valid = ", ".join(m.value for m in LidMode)
        raise ConfigError(f"lid.mode: ожидается одно из [{valid}], получено {raw_mode!r}")
    lid = LidSpec(
        mode=mode,
        wall=float(raw["wall"]),
        clearance=float(raw["clearance"]),
        top_gap=float(raw["top_gap"]),
        skirt=float(raw["skirt"]),
        snap=bool(raw["snap"]),
        snap_protrusion=float(raw["snap_protrusion"]),
        pin_diameter=float(raw["pin_diameter"]),
        pin_length=float(raw["pin_length"]),
        ear_thickness=float(raw["ear_thickness"]),
        hinge_clearance=float(raw["hinge_clearance"]),
    )
    if mode is not LidMode.NONE:
        _require_positive(lid.wall, "lid.wall")
        _require_positive(lid.skirt, "lid.skirt")
    if mode is LidMode.HINGED:
        _require_positive(lid.pin_diameter, "lid.pin_diameter")
        _require_positive(lid.pin_length, "lid.pin_length")
        _require_positive(lid.ear_thickness, "lid.ear_thickness")
    return lid


def _build_foot(raw: Dict[str, Any]) -> FootSpec:
    raw_mode = str(raw["mode"]).lower()
    try:
        mode = FootMode(raw_mode)
    except ValueError:
        valid = ", ".join(m.value for m in FootMode)
        raise ConfigError(f"foot.mode: ожидается одно из [{valid}], получено {raw_mode!r}")
    foot = FootSpec(
        mode=mode,
        thickness=float(raw["thickness"]),
        margin=float(raw["margin"]),
        min_margin=float(raw["min_margin"]),
        tip_angle_deg=float(raw["tip_angle_deg"]),
        chamfer=float(raw["chamfer"]),
    )
    if mode is not FootMode.NONE:
        _require_positive(foot.thickness, "foot.thickness")
    if mode is FootMode.AUTO and not 0 < foot.tip_angle_deg < 45:
        raise ConfigError(f"foot.tip_angle_deg: нужно в (0, 45), получено {foot.tip_angle_deg}")
    return foot


def _clamp_soft(value: float, lo: float, hi: float, name: str, unit: str = "") -> float:
    """Мягко зажать значение в [lo, hi] с жёлтым WARNING при выходе за диапазон.

    Конвенция проекта: подбираемые величины не валят сборку — корректируем и предупреждаем.
    """
    if value < lo:
        _log.warning("%s: %g%s вне диапазона — поднимаю до %g%s.", name, value, unit, lo, unit)
        return lo
    if value > hi:
        _log.warning("%s: %g%s вне диапазона — ограничиваю до %g%s.", name, value, unit, hi, unit)
        return hi
    return value


def _build_drill_geometry(raw: Dict[str, Any]) -> DrillGeometrySpec:
    """Собрать параметры 3D-моделей свёрел. Значения мягко зажимаются в безопасные диапазоны.

    Принципиально невозможного тут нет (фича целиком опциональна, геометрия сама деградирует на
    цилиндр при сбое), поэтому ConfigError не бросаем — только авто-коррекция + WARNING.
    """
    enabled = bool(raw["enabled"])
    raw_style = str(raw["style"]).lower()
    try:
        style = DrillStyle(raw_style)
    except ValueError:
        valid = ", ".join(s.value for s in DrillStyle)
        raise ConfigError(f"drill_geometry.style: ожидается одно из [{valid}], получено {raw_style!r}")
    # flutes — целое; ниже 2 канавок не бывает у спирального сверла, выше 4 loft рвётся/нереалистично.
    flutes = int(_clamp_soft(int(raw["flutes"]), 2, 4, "drill_geometry.flutes"))
    # helix>45° даёт крошечный шаг винта → гигантский twist → loft самопересекается; <5° — почти прямые.
    helix = _clamp_soft(float(raw["helix_angle_deg"]), 5.0, 45.0, "drill_geometry.helix_angle_deg", "°")
    # point=180° → плоский торец (tip_h→∞ при делении на tan); держим в разумных пределах сверла.
    point = _clamp_soft(float(raw["point_angle_deg"]), 60.0, 175.0, "drill_geometry.point_angle_deg", "°")
    # глубже 0.45·r резец проходит за центр и сечение распадается; мельче 0.1 — канавки не видно.
    depth_ratio = _clamp_soft(float(raw["flute_depth_ratio"]), 0.1, 0.45, "drill_geometry.flute_depth_ratio")
    return DrillGeometrySpec(
        enabled=enabled,
        style=style,
        flutes=flutes,
        helix_angle_deg=helix,
        point_angle_deg=point,
        flute_depth_ratio=depth_ratio,
    )


def _validate_spring_grip(drills: List[Drill], springs: SpringSpec, socket: SocketSpec) -> None:
    """Проверить ЗАЖИМ детента — единственное принципиально невозможное (авто-починить нельзя).

    Детент должен выступать за посадочный зазор внутрь хвостовика, иначе он его не касается и
    фиксации нет. От диаметра сверла это не зависит, поэтому проверяем глобально и жёстко
    (:class:`ConfigError`). Зазор разный: круглый — ``clearance``, hex — ``hex_clearance``.

    Всё остальное (число лепестков/рядов, ширина лепестка под мелкий бор) подгоняется ПЕР-ГНЕЗДОВО
    в :func:`drillholder.layout.fit_springs` на этапе геометрии — мелкое сверло получает узкий
    язычок, а не урезает фиксацию крупным гнёздам и не валит сборку."""
    if any(d.shank is ShankType.ROUND for d in drills) and springs.bump_protrusion - socket.clearance <= 0:
        raise ConfigError(
            f"springs.bump_protrusion ({springs.bump_protrusion}) <= socket.clearance "
            f"({socket.clearance}): детент не достаёт до круглого хвостовика (нет зажима). "
            f"Увеличьте bump_protrusion."
        )
    if any(d.shank is ShankType.HEX for d in drills) and springs.bump_protrusion - socket.hex_clearance <= 0:
        raise ConfigError(
            f"springs.bump_protrusion ({springs.bump_protrusion}) <= socket.hex_clearance "
            f"({socket.hex_clearance}): детент не достаёт до hex-хвостовика (нет зажима). "
            f"Увеличьте bump_protrusion."
        )


def _build_base(raw: Dict[str, Any]) -> BaseSpec:
    return BaseSpec(
        floor=_require_positive(raw["floor"], "base.floor"),
        min_height=_require_positive(raw["min_height"], "base.min_height"),
    )


def load_config(path: str = "holder_config.py") -> Tuple[List[Drill], Specs]:
    """Удобная обёртка: загрузить файл и сразу собрать ``(drills, specs)``."""
    return build_specs(load_raw_config(path))
