"""Тесты чистого разбора массового ввода диаметров (без Qt)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drillholder.gui.bulk_input import parse_diameters  # noqa: E402


def test_parses_user_example():
    text = "1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 5.5"
    values, errors = parse_diameters(text)
    assert errors == []
    assert values == [
        1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 5.5
    ]


def test_mixed_separators_commas_spaces_newlines_semicolons():
    values, errors = parse_diameters("1,2 3\n4;5\t6")
    assert errors == []
    assert values == [1, 2, 3, 4, 5, 6]


def test_preserves_order_without_sorting():
    # Сортировку делает виджет, парсер сохраняет порядок появления.
    values, _ = parse_diameters("10, 1, 5.5")
    assert values == [10, 1, 5.5]


def test_keeps_duplicates():
    values, _ = parse_diameters("3, 3, 3.5, 3")
    assert values == [3, 3, 3.5, 3]


def test_collects_unparseable_tokens():
    values, errors = parse_diameters("1, abc, 2, , 3x, 4")
    assert values == [1, 2, 4]
    assert errors == ["abc", "3x"]


def test_rejects_nonpositive():
    values, errors = parse_diameters("0, -1, 2")
    assert values == [2]
    assert errors == ["0", "-1"]


def test_empty_input():
    assert parse_diameters("   \n  ") == ([], [])
