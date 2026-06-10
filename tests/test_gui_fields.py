"""Тесты чистого слоя GUI — декларации полей и движок зависимостей, без Qt.

Покрывают требование «каждый параметр конфига отражён в форме»: для каждой секции ``DEFAULTS``
должен быть ровно один ``FieldSpec`` на ключ (и наоборот). Плюс smoke применимости/валидности.
Qt здесь не импортируется — модули fields/dependencies чистые (package __init__ ленив).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drillholder.config import DEFAULTS, deep_merge  # noqa: E402
from drillholder.gui.dependencies import (  # noqa: E402
    disabled_fields,
    invalid_fields,
    run_validation,
)
from drillholder.gui.fields import (  # noqa: E402
    TOOLTIP_WIDTH,
    Kind,
    build_field_specs,
    wrap_tooltip,
)

_SECTIONS = ["socket", "springs", "layout", "base", "lid", "foot", "drill_geometry", "labels", "rings", "output"]


def _specs_by_section():
    by_section = {}
    for spec in build_field_specs():
        by_section.setdefault(spec.section, {})[spec.key] = spec
    return by_section


def test_every_defaults_key_has_a_field_spec():
    """Каждый ключ каждой секции DEFAULTS покрыт FieldSpec и наоборот (без лишних/забытых)."""
    by_section = _specs_by_section()
    for section in _SECTIONS:
        expected = set(DEFAULTS[section].keys())
        actual = set(by_section.get(section, {}).keys())
        assert actual == expected, f"секция {section}: {expected ^ actual}"


def test_top_level_default_shank_has_spec():
    by_section = _specs_by_section()
    assert "default_shank" in by_section.get("", {})


def test_choice_specs_have_choices():
    for spec in build_field_specs():
        if spec.kind is Kind.CHOICE:
            assert spec.choices is not None, f"{spec.section}.{spec.key}: нет choices"


def test_every_choice_value_has_russian_label():
    """Каждое значение каждого выпадающего списка имеет русскую подпись (нет англ. фолбэка)."""
    from drillholder.gui.fields import CHOICE_LABELS, choice_display
    for spec in build_field_specs():
        if spec.kind is Kind.CHOICE:
            assert spec.choices in CHOICE_LABELS, f"{spec.section}.{spec.key}: класс не переведён"
            for member in spec.choices:
                assert member in CHOICE_LABELS[spec.choices], f"{spec.section}.{spec.key}: нет {member}"
                # Подпись — перевод, а не само англ. значение.
                assert choice_display(member) != member.value


def test_choice_labels_no_cross_enum_collision():
    """Разные str-Enum с одинаковым значением (center/front/back) не путают подписи."""
    from drillholder.model import LabelPosition, LabelReference, RowAlign
    from drillholder.gui.fields import choice_display
    assert choice_display(RowAlign.CENTER) == "по центру"
    assert choice_display(LabelReference.CENTER) == "от центра отверстия"
    assert choice_display(RowAlign.FRONT) == "по переднему краю"
    assert choice_display(LabelPosition.FRONT) == "спереди"


def test_specs_have_tooltips():
    """Tooltip берётся из render._CONFIG_SECTIONS — он должен быть непустым для всех полей."""
    for spec in build_field_specs():
        assert spec.tooltip, f"{spec.section}.{spec.key}: пустой tooltip"


def test_wrap_tooltip_breaks_long_lines():
    long = "слово " * 60  # одна длинная строка без переносов
    wrapped = wrap_tooltip(long)
    assert "\n" in wrapped
    assert all(len(line) <= TOOLTIP_WIDTH for line in wrapped.split("\n"))


def test_wrap_tooltip_preserves_explicit_newlines():
    wrapped = wrap_tooltip("Первый абзац короткий.\nВторой абзац короткий.")
    assert wrapped == "Первый абзац короткий.\nВторой абзац короткий."


def test_wrap_tooltip_empty():
    assert wrap_tooltip("") == ""


def test_all_field_tooltips_wrap_within_width():
    """Ни одна готовая подсказка формы не должна давать строку длиннее лимита после переноса."""
    for spec in build_field_specs():
        for line in wrap_tooltip(spec.tooltip).split("\n"):
            assert len(line) <= TOOLTIP_WIDTH, f"{spec.section}.{spec.key}: длинная строка {line!r}"


def _cfg(**overrides):
    return deep_merge(DEFAULTS, {"drills": [{"d": 3.0}], **overrides})


def test_disabled_angled_blocks_lid_body_keeps_mode():
    disabled = disabled_fields(_cfg(layout={"mode": "angled"}, lid={"mode": "hinged"}))
    assert ("lid", "wall") in disabled
    assert ("lid", "pin_diameter") in disabled
    assert ("lid", "mode") not in disabled  # селектор оставляем активным — чтобы снять конфликт


def test_disabled_grid_enables_align_and_grid_cols():
    disabled = disabled_fields(_cfg(layout={"mode": "grid"}))
    assert ("layout", "align") not in disabled      # align применяется и к grid (внутри ряда)
    assert ("layout", "grid_cols") not in disabled
    assert ("layout", "row_gap") not in disabled
    assert ("layout", "angle_deg") in disabled


def test_disabled_row_blocks_grid_only_fields():
    disabled = disabled_fields(_cfg(layout={"mode": "row"}))
    assert ("layout", "grid_cols") in disabled
    assert ("layout", "row_gap") in disabled
    assert ("layout", "align") not in disabled


def test_disabled_foot_none_blocks_foot_body():
    disabled = disabled_fields(_cfg(foot={"mode": "none"}))
    assert ("foot", "thickness") in disabled
    assert ("foot", "margin") in disabled
    assert ("foot", "mode") not in disabled


def test_disabled_foot_manual_vs_auto():
    manual = disabled_fields(_cfg(foot={"mode": "manual"}))
    assert ("foot", "min_margin") in manual
    assert ("foot", "tip_angle_deg") in manual
    assert ("foot", "margin") not in manual
    auto = disabled_fields(_cfg(foot={"mode": "auto"}))
    assert ("foot", "margin") in auto
    assert ("foot", "tip_angle_deg") not in auto


def test_disabled_springs_off_blocks_body():
    disabled = disabled_fields(_cfg(springs={"enabled": False}))
    assert ("springs", "count") in disabled
    assert ("springs", "enabled") not in disabled


def test_invalid_depth_order_flags_both_fields():
    invalid = invalid_fields(_cfg(socket={"min_depth": 8.0, "max_depth": 5.0}))
    assert ("socket", "max_depth") in invalid
    assert ("socket", "min_depth") in invalid


def test_invalid_bump_radius_too_small():
    invalid = invalid_fields(_cfg(springs={"bump_protrusion": 0.5, "bump_radius": 0.1}))
    assert ("springs", "bump_radius") in invalid


def test_invalid_angle_out_of_range_only_when_angled():
    assert ("layout", "angle_deg") in invalid_fields(_cfg(layout={"mode": "angled", "angle_deg": 95.0}))
    assert ("layout", "angle_deg") not in invalid_fields(_cfg(layout={"mode": "row", "angle_deg": 95.0}))


def test_run_validation_accepts_default_like_config():
    error, _warnings = run_validation(_cfg())
    assert error is None


def test_run_validation_reports_config_error():
    error, _warnings = run_validation(_cfg(socket={"min_depth": 8.0, "max_depth": 5.0}))
    assert error is not None
    assert "max_depth" in error
