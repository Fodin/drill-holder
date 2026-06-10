"""Тесты справочника стандартных длин — чистый слой, без FreeCAD."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drillholder.lengths import DIN338_LENGTHS, standard_length  # noqa: E402


def test_exact_diameter_returns_table_value():
    assert standard_length(6.0) == DIN338_LENGTHS[6.0]
    assert standard_length(3.0) == DIN338_LENGTHS[3.0]


def test_intermediate_diameter_rounds_up_to_next_standard():
    # 5.2 мм между 5.0 и 5.5 → берём ближайший сверху стандарт (5.5).
    assert standard_length(5.2) == DIN338_LENGTHS[5.5]


def test_oversize_diameter_uses_longest():
    assert standard_length(99.0) == DIN338_LENGTHS[max(DIN338_LENGTHS)]


def test_nonpositive_diameter_uses_shortest():
    assert standard_length(0) == min(DIN338_LENGTHS.values())
    assert standard_length(-1) == min(DIN338_LENGTHS.values())


def test_monotonic_nondecreasing_in_diameter():
    prev = 0.0
    for d in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]:
        cur = standard_length(d)
        assert cur >= prev
        prev = cur
