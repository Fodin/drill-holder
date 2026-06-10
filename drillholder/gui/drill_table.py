"""Таблица свёрел — отдельный составной виджет (не скалярное поле, поэтому вне fields/widgets).

Колонки: диаметр, длина, хвостовик, подпись. Диаметр-правка автозаполняет пустые подпись и
длину (``"auto (N)"`` со справочной длиной по DIN 338, но в конфиг уходит именно ``"auto"``).
``get_drills``/``set_drills`` — мост к «сырому» конфигу (список словарей, как в ``DEFAULTS``).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

try:  # FreeCAD предоставляет шим `PySide`, отражающий установленную версию Qt.
    from PySide import QtWidgets
except Exception:  # noqa: BLE001
    try:
        from PySide6 import QtWidgets
    except Exception:  # noqa: BLE001
        from PySide2 import QtWidgets

from ..lengths import standard_length
from ..model import ShankType
from .bulk_input import parse_diameters
from .fields import choice_display

_AUTO = "auto"


def _fmt_diameter(d: float) -> str:
    """'3' для целых, '6.35' иначе — как подпись по умолчанию."""
    return f"{d:.2f}".rstrip("0").rstrip(".")


def _fmt_length(v: float) -> str:
    """Длина без лишних нулей ('93', '12.5')."""
    return f"{v:g}"


class DrillTableWidget(QtWidgets.QWidget):
    """Редактор списка свёрел: таблица 4×N + кнопки добавления/удаления.

    ``on_change`` вызывается при любой правке (диалог пересчитывает зависимости/валидацию —
    набор свёрел влияет на подгонку пружин). ``default_shank`` подставляется новым строкам.
    """

    def __init__(self, on_change: Callable[[], None], default_shank: str = "round") -> None:
        super().__init__()
        self._on_change = on_change
        self._default_shank = default_shank

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["d, мм", "длина, мм", "хвостовик", "подпись"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemChanged.connect(self._changed)
        self.table.itemSelectionChanged.connect(self._update_del_enabled)
        layout.addWidget(self.table)

        btns = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("+ сверло")
        self.del_btn = QtWidgets.QPushButton("– удалить")
        self.del_btn.setEnabled(False)
        add_btn.clicked.connect(self._on_add_clicked)
        self.del_btn.clicked.connect(self._remove_selected_row)
        btns.addWidget(add_btn)
        btns.addWidget(self.del_btn)
        btns.addStretch()
        layout.addLayout(btns)

    def set_default_shank(self, shank: str) -> None:
        self._default_shank = shank or "round"

    # ── Заполнение/чтение ──────────────────────────────────────────────────────
    def set_drills(self, drills: List[Dict[str, Any]]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for drill in drills or []:
            self._add_drill_row(drill)
        self.table.blockSignals(False)
        self._update_del_enabled()

    def add_diameters(self, text: str) -> tuple:
        """Разобрать массовый ввод и ДОПИСАТЬ диаметры строками в конец таблицы.

        Новый пакет сортируется по возрастанию (дубликаты сохраняются — у одного диаметра может
        быть несколько свёрел); существующие строки не трогаем. Длина — ``auto``, подпись и
        хвостовик — как при ручном вводе (подпись = диаметр, хвостовик = текущий по умолчанию).
        Возвращает ``(добавлено, нераспознанные_куски)`` для сообщения пользователю.
        """
        values, errors = parse_diameters(text)
        values.sort()  # стабильная сортировка сохраняет дубликаты рядом
        if values:
            self.table.blockSignals(True)
            for d in values:
                label = _fmt_diameter(d)
                self._add_drill_row({"d": label, "label": label})  # length=None → auto
            self.table.blockSignals(False)
            self._update_del_enabled()
            self._changed()
        return values, errors

    def get_drills(self) -> List[Dict[str, Any]]:
        drills: List[Dict[str, Any]] = []
        for r in range(self.table.rowCount()):
            d_item = self.table.item(r, 0)
            if d_item is None or not d_item.text().strip():
                continue
            length_item = self.table.item(r, 1)
            shank_widget = self.table.cellWidget(r, 2)
            label_item = self.table.item(r, 3)
            drill: Dict[str, Any] = {"d": float(d_item.text().replace(",", "."))}
            ltext = length_item.text().strip().lower() if length_item is not None else ""
            # "auto" / "auto (N)" / пусто → в конфиг уходит "auto"; иначе конкретное число.
            drill["length"] = _AUTO if (not ltext or ltext.startswith(_AUTO)) else float(ltext.replace(",", "."))
            drill["shank"] = shank_widget.currentData() if shank_widget else "round"
            if label_item is not None and label_item.text().strip():
                drill["label"] = label_item.text().strip()
            drills.append(drill)
        return drills

    # ── Строки ──────────────────────────────────────────────────────────────────
    def _add_drill_row(self, drill: Dict[str, Any]) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(drill.get("d", ""))))
        length = drill.get("length")
        if isinstance(length, str) and length.strip().lower().startswith(_AUTO) or length in (None, ""):
            length_text = self._auto_text(drill.get("d"))
        else:
            length_text = str(length)
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(length_text))
        shank = QtWidgets.QComboBox()
        # Русская подпись в списке, в userData — английское значение ("round"/"hex") для конфига.
        for s in ShankType:
            shank.addItem(choice_display(s), s.value)
        idx = shank.findData(str(drill.get("shank") or self._default_shank))
        shank.setCurrentIndex(idx if idx >= 0 else 0)
        shank.currentTextChanged.connect(self._changed)  # после setCurrentIndex — не дёргать при заполнении
        self.table.setCellWidget(r, 2, shank)
        self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(drill.get("label", ""))))

    def _on_item_changed(self, item: "QtWidgets.QTableWidgetItem") -> None:
        """При вводе диаметра — подставить подпись и длину, если они пусты/auto."""
        if item.column() != 0:
            return
        try:
            d = float(item.text().strip().replace(",", "."))
        except ValueError:
            return
        r = item.row()
        self.table.blockSignals(True)
        try:
            label = self.table.item(r, 3)
            if label is None or not label.text().strip():
                self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(_fmt_diameter(d)))
            length = self.table.item(r, 1)
            cur = length.text().strip().lower() if length is not None else ""
            if cur == "" or cur.startswith(_AUTO):
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(self._auto_text(d)))
        finally:
            self.table.blockSignals(False)

    def _auto_text(self, d_raw: Any) -> str:
        """Текст ячейки длины для авто-режима: ``"auto (N)"`` если диаметр известен, иначе ``"auto"``."""
        try:
            d = float(str(d_raw).replace(",", "."))
        except (TypeError, ValueError):
            return _AUTO
        return f"{_AUTO} ({_fmt_length(standard_length(d))})"

    def _remove_selected_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        # Выделяем строку, занявшую место удалённой (следующую за блоком), иначе — последнюю.
        # Привязка к минимальному из удалённых индексов: после сдвига там окажется «следующее».
        remaining = self.table.rowCount()
        if remaining:
            target = min(min(rows), remaining - 1)
            self.table.selectRow(target)
            self.table.setCurrentCell(target, 0)
        self._update_del_enabled()
        self._changed()

    def _update_del_enabled(self) -> None:
        self.del_btn.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def _on_add_clicked(self) -> None:
        self._add_drill_row({})
        self._changed()

    def _changed(self, *args) -> None:
        self._on_change()
