"""Лёгкая подсветка синтаксиса Python для редактора конфига в GUI-диалоге.

Вынесено из :mod:`drillholder.gui` как самостоятельная единица: чисто визуальная обязанность
(строки, числа, ключевые слова, ``#``-комментарии), не зависящая от логики диалога.

Реализована на ``re`` (а не QRegExp/QRegularExpression) — одинаково работает во всех привязках
PySide. Конфиг прост (без тройных строк/экранирования), поэтому такого разбора хватает.
"""

from __future__ import annotations

import re
from typing import List, Tuple

try:  # FreeCAD предоставляет шим `PySide`, отражающий установленную версию Qt.
    from PySide import QtGui
except Exception:  # noqa: BLE001
    try:
        from PySide6 import QtGui
    except Exception:  # noqa: BLE001
        from PySide2 import QtGui  # последний фолбэк; если и его нет — ImportError наружу

_STRING_RE = re.compile(r"\"[^\"]*\"|'[^']*'")
_NUMBER_RE = re.compile(r"\b\d+\.?\d*\b")
_KEYWORD_RE = re.compile(r"\b(True|False|None)\b")


def _char_format(color: str, *, bold: bool = False, italic: bool = False):
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(QtGui.QColor(color))
    if bold:
        fmt.setFontWeight(QtGui.QFont.Bold)
    fmt.setFontItalic(italic)
    return fmt


class PyHighlighter(QtGui.QSyntaxHighlighter):
    """Подсветка Python для редактора конфига (строки, числа, ключевые слова, ``#`` коммент)."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._string = _char_format("#a31515")
        self._number = _char_format("#1f6feb")
        self._keyword = _char_format("#0033b3", bold=True)
        self._comment = _char_format("#2e7d32", italic=True)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 — переопределение Qt
        spans: List[Tuple[int, int]] = []
        for m in _STRING_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self._string)
            spans.append((m.start(), m.end()))

        def outside(pos: int) -> bool:
            return not any(lo <= pos < hi for lo, hi in spans)

        for m in _NUMBER_RE.finditer(text):
            if outside(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._number)
        for m in _KEYWORD_RE.finditer(text):
            if outside(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._keyword)
        # Комментарий — первый '#', не попавший внутрь строки, и до конца строки.
        for i, ch in enumerate(text):
            if ch == "#" and outside(i):
                self.setFormat(i, len(text) - i, self._comment)
                break
