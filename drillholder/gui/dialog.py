"""Главный диалог правки конфига: 5 смысловых вкладок + read-only превью.

Форма покрывает каждый параметр конфига. После любой правки :meth:`_recompute` пересчитывает
применимость (дизейбл неприменимых полей), валидность (подсветка) и финальную проверку
``build_specs`` (блокировка кнопки «Создать»). По «Создать» текущий конфиг записывается в файл
(``render_config``) и возвращается для сборки — файл и сборка всегда отражают текущую форму.

Диалог знает про ``model``/``config``, но не про FreeCAD (Dependency Rule). Поднятие
``QApplication`` и headless-защита перенесены из прежнего ``gui.py`` без изменений — на них
завязан особый teardown в ``build_holder.py``.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any, Dict, List, Optional

try:  # FreeCAD предоставляет шим `PySide`, отражающий установленную версию Qt.
    from PySide import QtCore, QtWidgets
except Exception:  # noqa: BLE001
    try:
        from PySide6 import QtCore, QtWidgets
    except Exception:  # noqa: BLE001
        from PySide2 import QtCore, QtWidgets  # последний фолбэк; если и его нет — ImportError наружу


class SideTabs(QtWidgets.QWidget):
    """Вкладки сбоку: список заголовков слева + стопка страниц справа.

    Замена ``QTabWidget`` с верхним рядом вкладок: семь длинных русских заголовков туда не
    влезают и режутся в «...». Здесь заголовки лежат вертикальным списком с горизонтальным
    текстом (видны целиком на любом стиле платформы), ширина списка подгоняется под самый
    длинный пункт. Интерфейс повторяет нужное подмножество ``QTabWidget``: :meth:`addTab`,
    :meth:`currentWidget`, сигнал :attr:`currentChanged`.
    """

    currentChanged = QtCore.Signal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.list = QtWidgets.QListWidget()
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.stack = QtWidgets.QStackedWidget()
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.list)
        row.addWidget(self.stack, 1)
        self.list.currentRowChanged.connect(self._on_row)

    def addTab(self, widget: QtWidgets.QWidget, title: str) -> None:
        self.list.addItem(title)
        self.stack.addWidget(widget)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        # Список ровно по ширине самого длинного заголовка (+поля пункта), без обрезки.
        self.list.setFixedWidth(self.list.sizeHintForColumn(0) + 24)

    def _on_row(self, index: int) -> None:
        if index >= 0:
            self.stack.setCurrentIndex(index)
            self.currentChanged.emit(index)

    def currentWidget(self) -> Optional[QtWidgets.QWidget]:
        return self.stack.currentWidget()

from ..config import DEFAULTS, calibration_config, deep_merge, render_config
from .dependencies import disabled_fields, invalid_fields, run_validation
from .drill_table import DrillTableWidget
from .fields import build_field_specs
from .preview import ConfigPreview
from .widgets import FieldWidget, SectionForm

_log = logging.getLogger("drillholder")

# Вкладки: (заголовок, [секции конфига]). Свёрла и превью добавляются отдельно.
_TABS = [
    ("Раскладка и корпус", ["layout", "base"]),
    ("Гнёзда и пружины", ["socket", "springs"]),
    ("Крышка и основание", ["lid", "foot"]),
    ("Модели свёрел", ["drill_geometry"]),
    ("Подписи и декор", ["labels", "rings"]),
    ("Экспорт", ["output"]),
]


class HolderDialog(QtWidgets.QDialog):
    def __init__(self, raw: Dict[str, Any], config_path: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle("Подставка для свёрел")
        self.resize(740, 720)
        self._raw = raw
        self._config_path = config_path
        self._loading = True       # подавляет _recompute при первичном заполнении формы
        self._result: Optional[Dict[str, Any]] = None

        specs = build_field_specs()
        by_section: Dict[str, List] = {}
        for spec in specs:
            by_section.setdefault(spec.section, []).append(spec)

        self._section_forms: Dict[str, SectionForm] = {}
        self._widgets: Dict[tuple, FieldWidget] = {}

        root = QtWidgets.QVBoxLayout(self)
        self.tabs = SideTabs(self)  # вкладки слева списком — длинные заголовки видны целиком

        # ── Вкладка «Свёрла» (таблица + хвостовик по умолчанию) ───────────────
        self.ds_field = FieldWidget(by_section[""][0], self._recompute)
        self._widgets[("", "default_shank")] = self.ds_field
        self.table = DrillTableWidget(self._recompute)
        # Комбо показывает русскую подпись — новым строкам отдаём английское значение (get_value).
        self.ds_field.control.currentTextChanged.connect(
            lambda *_: self.table.set_default_shank(self.ds_field.get_value())
        )
        self.tabs.addTab(self._build_drills_tab(), "Свёрла")

        # ── Смысловые вкладки из секций ───────────────────────────────────────
        for title, sections in _TABS:
            self.tabs.addTab(self._build_sections_tab(sections, by_section), title)

        # ── Превью ────────────────────────────────────────────────────────────
        self.preview = ConfigPreview()
        self.tabs.addTab(self.preview, "Конфиг")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        root.addWidget(self.tabs)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self._ok_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self._ok_button.setText("Создать")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Отмена")
        # Кнопка калибровки слева (ActionRole) — собирает тестовый купон, не подставку.
        calib_btn = buttons.addButton(
            "Калибровочный купон…", QtWidgets.QDialogButtonBox.ActionRole
        )
        calib_btn.setToolTip(
            "Собрать тестовую деталь для подбора socket.clearance под ваш принтер "
            "(ваш конфиг не меняется)."
        )
        calib_btn.clicked.connect(self._on_calibration)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_from_raw()
        self._loading = False
        self._recompute()

    # ── Построение вкладок ──────────────────────────────────────────────────────
    def _build_drills_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        # Массовый ввод: вставить «1, 1.5, 2 …» и дописать в таблицу одним нажатием.
        bulk_row = QtWidgets.QHBoxLayout()
        self.bulk_input = QtWidgets.QLineEdit()
        self.bulk_input.setPlaceholderText("Список диаметров: 1, 1.5, 2, 2.5, 3 …")
        self.bulk_input.setClearButtonEnabled(True)
        self.bulk_input.returnPressed.connect(self._on_bulk_add)
        bulk_btn = QtWidgets.QPushButton("Добавить из списка")
        bulk_btn.clicked.connect(self._on_bulk_add)
        bulk_row.addWidget(self.bulk_input)
        bulk_row.addWidget(bulk_btn)
        layout.addLayout(bulk_row)

        layout.addWidget(self.table)
        ds_box = QtWidgets.QFormLayout()
        ds_box.addRow(self.ds_field.label, self.ds_field.control)
        layout.addLayout(ds_box)
        return tab

    def _on_bulk_add(self) -> None:
        """Разобрать поле массового ввода, дописать диаметры в таблицу, очистить поле."""
        text = self.bulk_input.text()
        if not text.strip():
            return
        added, errors = self.table.add_diameters(text)
        if errors:
            # Спокойное сообщение: что добавили и что не распознали (а не пугающая ошибка).
            QtWidgets.QMessageBox.information(
                self,
                "Добавление диаметров",
                f"Добавлено свёрел: {len(added)}.\nНе распознано и пропущено: "
                + ", ".join(errors),
            )
        self.bulk_input.clear()

    def _build_sections_tab(self, sections: List[str], by_section: Dict[str, List]) -> QtWidgets.QWidget:
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        for section in sections:
            form = SectionForm(section, by_section[section], self._recompute)
            self._section_forms[section] = form
            for key, fw in form.fields.items():
                self._widgets[(section, key)] = fw
            layout.addWidget(form)
        layout.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    # ── Синхронизация формы ⇄ конфига ───────────────────────────────────────────
    def _load_from_raw(self) -> None:
        """Заполнить все виджеты из ``self._raw`` (под флагом _loading — без пересчёта)."""
        raw = self._raw
        for (section, key), fw in self._widgets.items():
            if section == "":
                fw.set_value(raw.get(key))
            else:
                fw.set_value(raw[section][key])
        self.table.set_default_shank(str(raw.get("default_shank", "round")))
        self.table.set_drills(raw.get("drills", []))

    def result_config(self) -> Dict[str, Any]:
        """Собрать «сырой» конфиг из всех полей формы (копия исходного — неизвестные ключи целы)."""
        out = copy.deepcopy(self._raw)
        for (section, key), fw in self._widgets.items():
            if section == "":
                out[key] = fw.get_value()
            else:
                out.setdefault(section, {})[key] = fw.get_value()
        out["drills"] = self.table.get_drills()
        return out

    # ── Пересчёт зависимостей и валидации ────────────────────────────────────────
    def _recompute(self, *args) -> None:
        if self._loading:
            return
        cfg = self.result_config()

        disabled = disabled_fields(cfg)
        for keypair, fw in self._widgets.items():
            if keypair in disabled:
                fw.set_enabled(False, disabled[keypair])
            else:
                fw.set_enabled(True)

        invalid = invalid_fields(cfg)
        for keypair, fw in self._widgets.items():
            fw.set_invalid(invalid.get(keypair))

        error, warnings = run_validation(cfg)
        self._show_status(error, warnings)
        self._ok_button.setEnabled(error is None)

        if self.tabs.currentWidget() is self.preview:
            self.preview.refresh(cfg)

    def _show_status(self, error: Optional[str], warnings: List[str]) -> None:
        if error:
            self.status.setStyleSheet("color: #c0392b;")
            self.status.setText("⚠ " + error)
        elif warnings:
            self.status.setStyleSheet("color: #8a6d00;")
            self.status.setText("\n".join(warnings))
        else:
            self.status.setStyleSheet("color: #2e7d32;")
            self.status.setText("Параметры корректны — можно создавать.")

    def _on_tab_changed(self, _index: int) -> None:
        if self.tabs.currentWidget() is self.preview:
            self.preview.refresh(self.result_config())

    # ── Калибровочный купон ──────────────────────────────────────────────────────
    def _on_calibration(self) -> None:
        """Собрать тестовый купон посадки вместо подставки (конфиг пользователя не трогаем).

        Возвращаем из диалога конфиг купона (слитый с DEFAULTS, чтобы прошёл build_specs) и
        закрываем через ``super().accept()`` — в обход :meth:`accept`, поэтому holder_config.py
        не перезаписывается. Сборку купона выполнит ``build_holder`` по этому конфигу.
        """
        answer = QtWidgets.QMessageBox.question(
            self,
            "Калибровка посадки",
            "Собрать калибровочный купон посадки?\n\n"
            "Это отдельная тестовая деталь — гребёнка гнёзд под разные зазоры (пружины выкл), "
            "а НЕ ваша подставка. Текущие настройки и holder_config.py не меняются.\n\n"
            "Напечатайте купон, найдите наименьший зазор, при котором сверло входит свободно "
            "без люфта, и впишите его в «Гнёзда → clearance».",
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
        )
        if answer != QtWidgets.QMessageBox.Ok:
            return
        self._result = deep_merge(DEFAULTS, calibration_config())
        super().accept()  # закрыть БЕЗ записи файла (минуя self.accept)

    # ── Принятие диалога: запись файла + возврат конфига ─────────────────────────
    def accept(self) -> None:  # noqa: D401 — переопределение QDialog.accept
        cfg = self.result_config()
        error, _ = run_validation(cfg)  # страховка: Ok и так блокируется при ошибке
        if error:
            QtWidgets.QMessageBox.warning(self, "Конфиг невалиден", error)
            return
        self._write_config_file(cfg)
        self._result = cfg
        super().accept()

    def _write_config_file(self, cfg: Dict[str, Any]) -> None:
        """Записать текущий конфиг в файл (как при сборке). Сбой записи не отменяет сборку."""
        path = self._config_path
        if not path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Сохранить конфиг", "holder_config.py", "Python (*.py)"
            )
            if not path:
                _log.warning("Файл конфига не выбран — сборка по текущим значениям без записи.")
                return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render_config(cfg))
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Ошибка записи", str(exc))
            return
        self._config_path = path
        _log.info("Конфиг записан: %s", path)

    def result(self) -> Optional[Dict[str, Any]]:
        return self._result


_HEADLESS_PLATFORMS = {"offscreen", "minimal", ""}


def show_dialog(raw: Dict[str, Any], config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Показать диалог. Вернуть изменённый конфиг или ``None``, если отменён.

    Поднимает собственный ``QApplication``, если его ещё нет (так диалог работает и из
    headless ``freecadcmd``, а не только как макрос в GUI FreeCAD). На безоконной Qt-платформе
    (``offscreen``/``minimal``) окно показать нельзя: бросаем понятную ошибку, чтобы вызывающая
    сторона откатилась на конфиг. ``config_path`` — путь файла для записи по «Создать».
    """
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    platform = app.platformName() if hasattr(app, "platformName") else ""
    if platform in _HEADLESS_PLATFORMS:
        raise RuntimeError(
            f"Qt-платформа '{platform or 'не определена'}' не отображает окон "
            "(нет дисплея). Запустите в графической сессии или снимите QT_QPA_PLATFORM=offscreen."
        )
    dlg = HolderDialog(raw, config_path)
    accepted = dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
    return dlg.result() if accepted else None
