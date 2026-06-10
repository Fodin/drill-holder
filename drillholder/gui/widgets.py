"""Qt-виджеты формы: один :class:`FieldWidget` на параметр, :class:`SectionForm` на секцию.

Виджеты строятся по декларациям :mod:`drillholder.gui.fields` (тип, диапазон, tooltip).
Каждый :class:`FieldWidget` умеет читать/писать своё значение в типе, который ждёт ``DEFAULTS``,
включаться/выключаться (с причиной в tooltip) и подсвечиваться невалидным (рамка + сообщение).
Единый колбэк ``on_change`` вызывается при любой правке — диалог по нему пересчитывает
зависимости и валидацию.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

try:  # FreeCAD предоставляет шим `PySide`, отражающий установленную версию Qt.
    from PySide import QtWidgets
except Exception:  # noqa: BLE001
    try:
        from PySide6 import QtWidgets
    except Exception:  # noqa: BLE001
        from PySide2 import QtWidgets  # последний фолбэк; если и его нет — ImportError наружу

from .fields import SECTION_TITLES, FieldSpec, Kind, choice_display, wrap_tooltip

_FORMATS = ["FCStd", "STL", "STEP"]
_INVALID_BORDER = "border: 1px solid #c0392b;"  # красная рамка для невалидного поля
_INVALID_LABEL = "color: #c0392b;"


class FieldWidget:
    """Обёртка одного параметра: подпись (``label``) + элемент управления (``control``).

    Не наследует QWidget — держит готовые виджеты для размещения в ``QFormLayout`` и
    инкапсулирует чтение/запись значения, доступность и подсветку невалидности.
    """

    def __init__(self, spec: FieldSpec, on_change: Callable[[], None]) -> None:
        self.spec = spec
        self.label = QtWidgets.QLabel(spec.label)
        self._fmt_checks: Dict[str, QtWidgets.QCheckBox] = {}
        self._line: Optional[QtWidgets.QLineEdit] = None
        self.control = self._build_control()
        self._base_tooltip = spec.tooltip
        self._disabled_reason = ""
        self._invalid_msg = ""
        if spec.tooltip:
            self._apply_tooltip(spec.tooltip)
        self._connect(on_change)

    # ── Построение control по типу ───────────────────────────────────────────
    def _build_control(self) -> QtWidgets.QWidget:
        k = self.spec.kind
        if k is Kind.FLOAT:
            w = QtWidgets.QDoubleSpinBox()
            w.setDecimals(self.spec.decimals)
            w.setRange(self.spec.minimum, self.spec.maximum)
            w.setSingleStep(self.spec.step)
            return w
        if k is Kind.INT:
            w = QtWidgets.QSpinBox()
            w.setRange(int(self.spec.minimum), int(self.spec.maximum))
            return w
        if k is Kind.BOOL:
            return QtWidgets.QCheckBox()
        if k is Kind.CHOICE:
            w = QtWidgets.QComboBox()
            # Показываем русскую подпись, в userData храним английское Enum-значение (для конфига).
            for e in self.spec.choices:  # type: ignore[union-attr]
                w.addItem(choice_display(e), e.value)
            return w
        if k is Kind.TEXT:
            self._line = QtWidgets.QLineEdit()
            return self._line
        if k is Kind.FONT:
            return self._build_font()
        if k is Kind.FORMATS:
            return self._build_formats()
        raise ValueError(f"неизвестный Kind: {k}")

    def _build_font(self) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        self._line = QtWidgets.QLineEdit()
        self._line.setPlaceholderText("пусто — системный шрифт автоматически")
        pick = QtWidgets.QPushButton("Система…")
        pick.setToolTip("Выбрать установленный в системе шрифт по имени")
        pick.clicked.connect(self._pick_system_font)
        browse = QtWidgets.QPushButton("Файл…")
        browse.setToolTip("Выбрать файл шрифта .ttf/.otf")
        browse.clicked.connect(self._browse_font)
        row.addWidget(self._line)
        row.addWidget(pick)
        row.addWidget(browse)
        return box

    def _build_formats(self) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        for f in _FORMATS:
            cb = QtWidgets.QCheckBox(f)
            self._fmt_checks[f] = cb
            row.addWidget(cb)
        row.addStretch()
        return box

    # ── Сигнал изменения ──────────────────────────────────────────────────────
    def _connect(self, on_change: Callable[[], None]) -> None:
        k = self.spec.kind
        if k in (Kind.FLOAT, Kind.INT):
            self.control.valueChanged.connect(on_change)
        elif k is Kind.BOOL:
            self.control.toggled.connect(on_change)
        elif k is Kind.CHOICE:
            self.control.currentTextChanged.connect(on_change)
        elif k in (Kind.TEXT, Kind.FONT):
            self._line.textChanged.connect(on_change)
        elif k is Kind.FORMATS:
            for cb in self._fmt_checks.values():
                cb.toggled.connect(on_change)

    # ── Чтение/запись значения ─────────────────────────────────────────────────
    def get_value(self) -> Any:
        k = self.spec.kind
        if k is Kind.FLOAT:
            return float(self.control.value())
        if k is Kind.INT:
            return int(self.control.value())
        if k is Kind.BOOL:
            return self.control.isChecked()
        if k is Kind.CHOICE:
            return self.control.currentData()  # английское Enum-значение из userData
        if k in (Kind.TEXT, Kind.FONT):
            return self._line.text().strip() if k is Kind.FONT else self._line.text()
        if k is Kind.FORMATS:
            return [f for f, cb in self._fmt_checks.items() if cb.isChecked()]
        raise ValueError(f"неизвестный Kind: {k}")

    def set_value(self, value: Any) -> None:
        k = self.spec.kind
        if k is Kind.FLOAT:
            self.control.setValue(float(value))
        elif k is Kind.INT:
            self.control.setValue(int(value))
        elif k is Kind.BOOL:
            self.control.setChecked(bool(value))
        elif k is Kind.CHOICE:
            idx = self.control.findData(str(value))  # ищем по англ. значению в userData
            self.control.setCurrentIndex(idx if idx >= 0 else 0)
        elif k in (Kind.TEXT, Kind.FONT):
            self._line.setText(str(value))
        elif k is Kind.FORMATS:
            wanted = {str(x).upper() for x in (value or [])}
            for f, cb in self._fmt_checks.items():
                cb.setChecked(f.upper() in wanted)

    # ── Доступность и валидность ────────────────────────────────────────────────
    def set_enabled(self, enabled: bool, reason: str = "") -> None:
        self.control.setEnabled(enabled)
        self.label.setEnabled(enabled)
        self._disabled_reason = "" if enabled else reason
        self._refresh_decoration()

    def set_invalid(self, message: Optional[str]) -> None:
        self._invalid_msg = message or ""
        self._refresh_decoration()

    def _refresh_decoration(self) -> None:
        invalid = bool(self._invalid_msg)
        self.control.setStyleSheet(_INVALID_BORDER if invalid else "")
        self.label.setStyleSheet(_INVALID_LABEL if invalid else "")
        parts = [self._base_tooltip] if self._base_tooltip else []
        if self._disabled_reason:
            parts.append("неактивно: " + self._disabled_reason)
        if self._invalid_msg:
            parts.append("⚠ " + self._invalid_msg)
        self._apply_tooltip("\n".join(parts))

    def _apply_tooltip(self, text: str) -> None:
        """Поставить подсказку на подпись и control, перенеся длинные строки по словам."""
        wrapped = wrap_tooltip(text)
        self.label.setToolTip(wrapped)
        self.control.setToolTip(wrapped)

    # ── Пикеры шрифта (для Kind.FONT) ────────────────────────────────────────────
    def _browse_font(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.control, "Выберите файл шрифта", "", "Шрифты (*.ttf *.otf)"
        )
        if path:
            self._line.setText(path)

    def _pick_system_font(self) -> None:
        # QFontDialog.getFont в разных привязках возвращает (font, ok) либо (ok, font).
        result = QtWidgets.QFontDialog.getFont()
        if isinstance(result[0], bool):
            ok, font = result
        else:
            font, ok = result
        if ok:
            self._line.setText(font.family())


class SectionForm(QtWidgets.QGroupBox):
    """Группа полей одной секции конфига в ``QFormLayout``.

    Заголовок — из :data:`fields.SECTION_TITLES`. Поля доступны по ключу через ``self.fields``.
    """

    def __init__(self, section: str, specs: List[FieldSpec], on_change: Callable[[], None]) -> None:
        super().__init__(SECTION_TITLES.get(section, section))
        self.section = section
        self.fields: Dict[str, FieldWidget] = {}
        form = QtWidgets.QFormLayout(self)
        # Поля тянутся на всю ширину колонки (иначе на macOS строка форматов FCStd/STL/STEP
        # упиралась в правый край и обрезала последний чекбокс).
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        for spec in specs:
            fw = FieldWidget(spec, on_change)
            self.fields[spec.key] = fw
            form.addRow(fw.label, fw.control)
