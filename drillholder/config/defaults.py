"""Встроенные значения по умолчанию для конфига.

Зеркалят пример ``holder_config.py`` и дефолты dataclass'ов из :mod:`drillholder.model`,
но заданы явно, чтобы отсутствующие в пользовательском конфиге ключи всегда имели значение.
При добавлении поля правьте все три места (см. CLAUDE.md).
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "drills": [],
    "default_shank": "round",  # тип хвостовика по умолчанию; в drills указывают только иной
    "socket": {
        "clearance": 0.20,
        "depth_ratio": 0.35,
        "min_depth": 8.0,
        "max_depth": 40.0,
        "hex_size": 6.35,
        "hex_clearance": 0.25,
        "hex_flat_up": True,
    },
    "springs": {
        "enabled": True,
        "count": 3,
        "rows": 2,
        "leaf_width": 1.8,
        "leaf_length": 5.0,
        "leaf_thickness": 1.0,
        "slot_width": 0.6,
        "relief_gap": 0.6,
        "bump_protrusion": 0.40,
        "bump_radius": 0.5,
    },
    "layout": {
        "mode": "auto",
        "grid_cols": 0,
        "serpentine": False,
        "angle_deg": 20.0,
        "pitch_extra": 4.0,
        "edge_margin": 6.0,
        "row_gap": 0.0,
        "align": "center",
    },
    "base": {"floor": 5.0, "min_height": 18.0},
    "lid": {
        "mode": "none",
        "wall": 2.0,
        "clearance": 0.4,
        "top_gap": 3.0,
        "skirt": 8.0,
        "snap": True,
        "snap_protrusion": 0.5,
        "pin_diameter": 4.0,
        "pin_length": 3.0,
        "ear_thickness": 3.0,
        "hinge_clearance": 0.4,
    },
    "foot": {
        "mode": "none",
        "thickness": 3.0,
        "margin": 8.0,
        "min_margin": 4.0,
        "tip_angle_deg": 15.0,
        "chamfer": 0.0,
    },
    "drill_geometry": {
        "enabled": False,
        "style": "spiral",
        "flutes": 2,
        "helix_angle_deg": 30.0,
        "point_angle_deg": 118.0,
        "flute_depth_ratio": 0.28,
    },
    "labels": {
        "enabled": True,
        "mode": "engrave",
        "position": "front",
        "reference": "edge",
        "size": 4.0,
        "depth": 0.6,
        "font": "",
        "offset": 2.0,
        "multicolor": False,
    },
    "rings": {
        "enabled": False,
        "width": 1.5,
        "depth": 0.6,
        "gap": 0.0,
    },
    "output": {
        "dir": ".",
        "name": "drill_holder",
        "formats": ["FCStd", "STL", "STEP"],
        "linear_deflection": 0.1,
        "angular_deflection": 0.5,
    },
}
