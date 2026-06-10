"""Вкладка-превью: только чтение сгенерированного ``holder_config.py``.

Показывает, какой именно конфиг уйдёт в сборку и будет записан в файл по кнопке «Создать».
Редактирования нет — источник истины теперь форма. Подсветка синтаксиса оставлена для
читаемости (тот же :class:`PyHighlighter`, что и раньше).
"""

from __future__ import annotations

from typing import Any, Dict

try:  # FreeCAD предоставляет шим `PySide`, отражающий установленную версию Qt.
    from PySide import QtWidgets, QtGui
except Exception:  # noqa: BLE001
    try:
        from PySide6 import QtWidgets, QtGui
    except Exception:  # noqa: BLE001
        from PySide2 import QtWidgets, QtGui

from ..config import render_config
from ..gui_highlighter import PyHighlighter


class ConfigPreview(QtWidgets.QWidget):
    """Read-only просмотр конфига, сгенерированного из текущего состояния формы."""

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.editor = QtWidgets.QPlainTextEdit()
        self.editor.setReadOnly(True)
        try:  # моноширинный шрифт для кода
            mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        except Exception:  # noqa: BLE001
            mono = QtGui.QFont("monospace")
            mono.setStyleHint(QtGui.QFont.Monospace)
        mono.setPointSize(13)
        self.editor.setFont(mono)
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        try:  # ширина табуляции в 4 пробела (имена методов различаются Qt5/Qt6)
            self.editor.setTabStopDistance(4 * self.editor.fontMetrics().horizontalAdvance(" "))
        except Exception:  # noqa: BLE001
            pass
        self._highlighter = PyHighlighter(self.editor.document())
        layout.addWidget(self.editor)
        layout.addWidget(QtWidgets.QLabel(
            "Только просмотр. Файл записывается по кнопке «Создать» из текущей формы."
        ))

    def refresh(self, cfg: Dict[str, Any]) -> None:
        self.editor.setPlainText(render_config(cfg))
