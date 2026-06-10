"""Тесты чистого слоя конфига — слияние с дефолтами и валидация, без FreeCAD."""

import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drillholder.config import (  # noqa: E402
    ConfigError,
    DEFAULTS,
    build_specs,
    deep_merge,
    load_raw_config,
)
from drillholder.model import (  # noqa: E402
    FootMode,
    LabelReference,
    LayoutMode,
    LidMode,
    RowAlign,
    ShankType,
)
from drillholder.layout import fit_springs, resolve_depth  # noqa: E402


def _fit_single(cfg):
    """Собрать конфиг и вернуть пер-гнездовую спеку пружин для его единственного сверла."""
    drills, specs = build_specs(cfg)
    return fit_springs(drills[0], resolve_depth(drills[0], specs), specs), specs


def test_deep_merge_nested_without_mutation():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 20}, "c": 4}
    merged = deep_merge(base, override)
    assert merged == {"a": {"x": 1, "y": 20}, "b": 3, "c": 4}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3}  # исходник не тронут


def _write_config(tmp_path, body: str) -> str:
    path = os.path.join(str(tmp_path), "holder_config.py")
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body))
    return path


def test_load_merges_over_defaults(tmp_path):
    path = _write_config(tmp_path, """
        CONFIG = {"drills": [{"d": 5.0, "length": 80}]}
    """)
    merged = load_raw_config(path)
    # Пользователь задал только drills — остальное из DEFAULTS.
    assert merged["drills"] == [{"d": 5.0, "length": 80}]
    assert merged["socket"]["depth_ratio"] == DEFAULTS["socket"]["depth_ratio"]
    assert merged["springs"]["enabled"] is True


def test_build_specs_happy_path(tmp_path):
    path = _write_config(tmp_path, """
        CONFIG = {"drills": [
            {"d": 3.0, "length": 60, "shank": "round", "label": "3"},
            {"d": 6.35, "length": 75, "shank": "hex"},
        ], "layout": {"mode": "grid"}}
    """)
    drills, specs = build_specs(load_raw_config(path))
    assert len(drills) == 2
    assert drills[1].shank is ShankType.HEX
    assert specs.layout.mode is LayoutMode.GRID
    assert specs.output.formats == ("FCStd", "STL", "STEP")


def test_missing_config_var_raises(tmp_path):
    path = _write_config(tmp_path, "X = 1\n")
    with pytest.raises(ConfigError, match="CONFIG"):
        load_raw_config(path)


def test_empty_drills_rejected():
    with pytest.raises(ConfigError, match="drills"):
        build_specs(deep_merge(DEFAULTS, {"drills": []}))


def test_negative_diameter_rejected():
    with pytest.raises(ConfigError, match="d"):
        build_specs(deep_merge(DEFAULTS, {"drills": [{"d": -1, "length": 50}]}))


def test_unknown_shank_rejected():
    with pytest.raises(ConfigError, match="shank"):
        build_specs(deep_merge(DEFAULTS, {"drills": [{"d": 3, "length": 50, "shank": "torx"}]}))


def test_unknown_format_rejected():
    cfg = deep_merge(DEFAULTS, {"drills": [{"d": 3, "length": 50}], "output": {"formats": ["OBJ"]}})
    with pytest.raises(ConfigError, match="formats"):
        build_specs(cfg)


def test_max_depth_below_min_rejected():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 3, "length": 50}],
        "socket": {"min_depth": 20, "max_depth": 10},
    })
    with pytest.raises(ConfigError, match="max_depth"):
        build_specs(cfg)


def test_springs_fit_reduces_count_for_thin_bore():
    # d=1.0 (бор r≈0.7) с дефолтными пружинами (count=3): 3 узких язычка не влезают по окружности,
    # пер-гнездовая подгонка ужимает count и ширину лепестка — но детент остаётся (не пропуск).
    sp, specs = _fit_single(deep_merge(DEFAULTS, {"drills": [{"d": 1.0, "length": 30}]}))
    assert sp is not None                      # пружина для 1 мм всё-таки есть
    assert sp.count < specs.springs.count      # лепестков меньше желаемого максимума
    assert sp.leaf_width < specs.springs.leaf_width  # ширина ужата под бор
    # Глобальная спека НЕ мутирует — остаётся желаемым максимумом.
    assert specs.springs.count == DEFAULTS["springs"]["count"]


def test_springs_fit_keeps_tiny_drill_with_small_leaf():
    # d=0.5: раньше была хард-ошибка; теперь лепесток ужимается и гнездо получает маленький детент.
    sp, specs = _fit_single(deep_merge(DEFAULTS, {"drills": [{"d": 0.5, "length": 30}]}))
    assert sp is not None
    assert sp.count >= 1
    assert sp.leaf_width < specs.springs.leaf_width


def test_springs_fit_reduces_rows_for_shallow_socket():
    # Глубины хватает на 1 ряд, но не на 2 → пер-гнездовая подгонка даёт rows=1.
    sp, _ = _fit_single(deep_merge(DEFAULTS, {
        "drills": [{"d": 8.0, "length": 40}],
        "socket": {"depth_ratio": 0.3, "min_depth": 12, "max_depth": 12},  # глубина 12 мм
        "springs": {"rows": 2, "leaf_length": 5.0},
    }))
    assert sp is not None and sp.rows == 1


def test_springs_disabled_allows_tiny_drill():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 1.0, "length": 30}],
        "springs": {"enabled": False},
    })
    drills, specs = build_specs(cfg)
    assert specs.springs.enabled is False
    assert drills[0].d == 1.0


def test_springs_fit_skipped_for_too_shallow_socket():
    # Гнездо мельче одного ряда → пер-гнездовая подгонка отдаёт None (гладкий бор), а не валит сборку.
    sp, _ = _fit_single(deep_merge(DEFAULTS, {
        "drills": [{"d": 8.0, "length": 20}],
        "socket": {"depth_ratio": 0.2, "min_depth": 4},  # глубина ~4 мм
        "springs": {"rows": 2, "leaf_length": 6.0},
    }))
    assert sp is None


def test_bump_protrusion_below_clearance_rejected():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 8.0, "length": 80}],
        "socket": {"clearance": 0.3},
        "springs": {"bump_protrusion": 0.2, "bump_radius": 0.6},
    })
    with pytest.raises(ConfigError, match="bump_protrusion"):
        build_specs(cfg)


def test_lid_and_foot_modes_parsed():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 8.0, "length": 80}],
        "lid": {"mode": "hinged"},
        "foot": {"mode": "auto"},
    })
    _, specs = build_specs(cfg)
    assert specs.lid.mode is LidMode.HINGED
    assert specs.foot.mode is FootMode.AUTO


def test_lid_rejected_for_angled_layout():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 8.0, "length": 80}],
        "layout": {"mode": "angled"},
        "lid": {"mode": "removable"},
    })
    with pytest.raises(ConfigError, match="angled"):
        build_specs(cfg)


def test_layout_align_parsed_and_defaults_center():
    base = deep_merge(DEFAULTS, {"drills": [{"d": 6.0, "length": 80}]})
    _, specs = build_specs(base)
    assert specs.layout.align is RowAlign.CENTER  # дефолт
    _, specs_front = build_specs(deep_merge(base, {"layout": {"align": "front"}}))
    assert specs_front.layout.align is RowAlign.FRONT


def test_unknown_layout_align_rejected():
    cfg = deep_merge(DEFAULTS, {"drills": [{"d": 6.0, "length": 80}], "layout": {"align": "middle"}})
    with pytest.raises(ConfigError, match="layout.align"):
        build_specs(cfg)


def test_unknown_lid_mode_rejected():
    cfg = deep_merge(DEFAULTS, {"drills": [{"d": 8.0, "length": 80}], "lid": {"mode": "sliding"}})
    with pytest.raises(ConfigError, match="lid.mode"):
        build_specs(cfg)


def test_default_shank_applied_and_overridden():
    cfg = deep_merge(DEFAULTS, {
        "default_shank": "hex",
        "drills": [
            {"d": 6.35, "length": 75},                 # без shank → hex (дефолт)
            {"d": 5.0, "length": 80, "shank": "round"},  # явный round
        ],
    })
    drills, _ = build_specs(cfg)
    assert drills[0].shank is ShankType.HEX
    assert drills[1].shank is ShankType.ROUND


def test_length_auto_resolves_to_standard():
    from drillholder.lengths import standard_length
    cfg = deep_merge(DEFAULTS, {
        "drills": [
            {"d": 6.0, "length": "auto"},  # явный auto
            {"d": 5.0},                     # length вовсе не задана
        ],
    })
    drills, _ = build_specs(cfg)
    assert drills[0].length == standard_length(6.0)
    assert drills[1].length == standard_length(5.0)


def test_explicit_length_overrides_standard():
    cfg = deep_merge(DEFAULTS, {"drills": [{"d": 6.0, "length": 200}]})
    drills, _ = build_specs(cfg)
    assert drills[0].length == 200.0


def test_hex_drill_keeps_springs_for_axial_retention():
    # У hex детенты остаются (осевая фиксация — чтобы хвостовик не выпадал); диаметр сверла на
    # подгонку не влияет (грань зависит только от hex_size). Дефолтные 3 детента влезают на грани.
    cfg = deep_merge(DEFAULTS, {"drills": [{"d": 2.0, "length": 50, "shank": "hex"}]})
    drills, specs = build_specs(cfg)
    assert drills[0].shank is ShankType.HEX
    assert specs.springs.enabled
    assert specs.springs.count == DEFAULTS["springs"]["count"]


def test_hex_springs_capped_at_six_flats():
    # Детентов не может быть больше 6 граней — пер-гнездовая подгонка ограничивает count до 6.
    sp, _ = _fit_single(deep_merge(DEFAULTS, {
        "drills": [{"d": 5.0, "length": 60, "shank": "hex"}],
        "springs": {"count": 9},
    }))
    assert sp is not None and sp.count == 6


def test_hex_springs_grip_uses_hex_clearance():
    # Если детент не достаёт за hex_clearance до грани хвостовика — хард-ошибка (нет зажима).
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 5.0, "length": 60, "shank": "hex"}],
        "socket": {"hex_clearance": 0.5},
        "springs": {"bump_protrusion": 0.4, "bump_radius": 0.5},
    })
    with pytest.raises(ConfigError, match="hex_clearance"):
        build_specs(cfg)


def test_socket_hex_size_parsed_and_validated():
    _, specs = build_specs(deep_merge(DEFAULTS, {
        "drills": [{"d": 5.0, "length": 60, "shank": "hex"}],
        "socket": {"hex_size": 8.0},
    }))
    assert specs.socket.hex_size == 8.0
    with pytest.raises(ConfigError, match="hex_size"):
        build_specs(deep_merge(DEFAULTS, {
            "drills": [{"d": 5.0, "length": 60, "shank": "hex"}],
            "socket": {"hex_size": 0},
        }))


def test_render_config_documents_and_roundtrips():
    from drillholder.config import render_config
    cfg = deep_merge(DEFAULTS, {"drills": [
        {"d": 6.0, "length": "auto", "shank": "round", "label": "6.0"},
        {"d": 5.0, "length": 75.0, "shank": "hex"},
    ]})
    text = render_config(cfg)

    # Самодокументирован: есть комментарии и пояснения (не голый dump).
    assert text.count("#") > 20
    assert "DIN 338" in text
    # Ровные 4-пробельные отступы секций (а не pprint-выравнивание по скобке).
    assert '\n    "socket": {' in text
    assert '\n        "clearance":' in text

    # Полный round-trip: парсится обратно в тот же конфиг.
    ns: dict = {}
    exec(compile(text, "<rendered>", "exec"), ns)
    reloaded = deep_merge(DEFAULTS, ns["CONFIG"])
    drills, _ = build_specs(reloaded)
    assert [d.d for d in drills] == [6.0, 5.0]          # порядок drills сохранён
    assert ns["CONFIG"]["drills"][0]["length"] == "auto"  # auto остаётся auto, не подменяется числом
    assert ns["CONFIG"]["drills"][1]["shank"] == "hex"


def test_labels_reference_parsed():
    _, specs = build_specs(deep_merge(DEFAULTS, {
        "drills": [{"d": 6.0, "length": 80}],
        "labels": {"reference": "center"},
    }))
    assert specs.labels.reference is LabelReference.CENTER
    # Дефолт — от края отверстия.
    _, specs_def = build_specs(deep_merge(DEFAULTS, {"drills": [{"d": 6.0, "length": 80}]}))
    assert specs_def.labels.reference is LabelReference.EDGE
    with pytest.raises(ConfigError, match="labels.reference"):
        build_specs(deep_merge(DEFAULTS, {
            "drills": [{"d": 6.0, "length": 80}],
            "labels": {"reference": "face"},  # face удалён → ошибка
        }))


def test_angled_requires_valid_angle():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 3, "length": 50}],
        "layout": {"mode": "angled", "angle_deg": 0},
    })
    with pytest.raises(ConfigError, match="angle"):
        build_specs(cfg)


def test_drill_geometry_default_disabled():
    # Фича по умолчанию выключена и не зависит от того, задана ли секция в конфиге.
    from drillholder.model import DrillStyle
    _, specs = build_specs(deep_merge(DEFAULTS, {"drills": [{"d": 6.0, "length": 80}]}))
    assert specs.drill_geometry.enabled is False
    assert specs.drill_geometry.style is DrillStyle.SPIRAL  # дефолтная форма — спираль
    assert specs.drill_geometry.flutes == 2
    assert specs.drill_geometry.point_angle_deg == 118.0


def test_drill_geometry_style_cylinder_parsed():
    from drillholder.model import DrillStyle
    _, specs = build_specs(deep_merge(DEFAULTS, {
        "drills": [{"d": 6.0, "length": 80}],
        "drill_geometry": {"enabled": True, "style": "cylinder"},
    }))
    assert specs.drill_geometry.style is DrillStyle.CYLINDER


def test_drill_geometry_unknown_style_rejected():
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 6.0, "length": 80}],
        "drill_geometry": {"enabled": True, "style": "twist"},
    })
    with pytest.raises(ConfigError, match="drill_geometry.style"):
        build_specs(cfg)


def test_drill_geometry_parsed():
    _, specs = build_specs(deep_merge(DEFAULTS, {
        "drills": [{"d": 6.0, "length": 80}],
        "drill_geometry": {"enabled": True, "flutes": 3, "helix_angle_deg": 25.0},
    }))
    assert specs.drill_geometry.enabled is True
    assert specs.drill_geometry.flutes == 3
    assert specs.drill_geometry.helix_angle_deg == 25.0


def test_drill_geometry_soft_clamps_out_of_range(caplog):
    # Конвенция: выходящие за диапазон значения мягко зажимаются + WARNING, без ConfigError.
    import logging
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 6.0, "length": 80}],
        "drill_geometry": {
            "enabled": True,
            "flutes": 10,            # → 4
            "helix_angle_deg": 80.0,  # → 45
            "point_angle_deg": 200.0,  # → 175
            "flute_depth_ratio": 0.9,  # → 0.45
        },
    })
    with caplog.at_level(logging.WARNING, logger="drillholder"):
        _, specs = build_specs(cfg)
    assert specs.drill_geometry.flutes == 4
    assert specs.drill_geometry.helix_angle_deg == 45.0
    assert specs.drill_geometry.point_angle_deg == 175.0
    assert specs.drill_geometry.flute_depth_ratio == 0.45
    assert any("drill_geometry" in r.message for r in caplog.records)


def test_drill_geometry_roundtrips_through_render():
    from drillholder.config import render_config
    cfg = deep_merge(DEFAULTS, {
        "drills": [{"d": 6.0, "length": 80}],
        "drill_geometry": {"enabled": True, "flutes": 3},
    })
    text = render_config(cfg)
    assert '"drill_geometry": {' in text
    ns: dict = {}
    exec(compile(text, "<rendered>", "exec"), ns)
    _, specs = build_specs(deep_merge(DEFAULTS, ns["CONFIG"]))
    assert specs.drill_geometry.enabled is True
    assert specs.drill_geometry.flutes == 3
