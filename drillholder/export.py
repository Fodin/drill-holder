"""Экспорт готовых деталей в выбранные форматы — адаптер к FreeCAD.

Формат — сменная деталь: ядро ничего о нём не знает, набор задаётся в :class:`OutputSpec`.
При нескольких деталях (корпус + крышка) FCStd хранит всё в одном файле, а STL/STEP пишутся
по отдельному файлу на деталь (удобно для печати) с суффиксом имени.
"""

from __future__ import annotations

import os
from typing import List, Tuple

import FreeCAD as App

from .model import OutputSpec

_EXT = {"FCStd": ".FCStd", "STL": ".stl", "STEP": ".step"}


def _fresh(path: str) -> None:
    """Удалить существующий файл перед записью, чтобы экспорт создавал новый inode.

    ``exportStep``/``mesh.write`` перезаписывают файл на месте (тот же inode) — тогда mtime
    обновляется, а время создания (birth) остаётся от первого запуска. Сносим цель заранее:
    каждый прогон даёт свежее время создания (как у FCStd, который пишется через temp+rename).
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def export_model(doc, parts: List[Tuple[str, object]], output: OutputSpec) -> List[str]:
    """Записать детали в каждый формат из ``output.formats``. Возвращает пути файлов."""
    os.makedirs(output.directory, exist_ok=True)
    multi = len(parts) > 1
    written: List[str] = []

    for fmt in output.formats:
        if fmt == "FCStd":
            from .geometry.camera import inject_camera, read_gui_document_xml

            path = os.path.join(output.directory, output.name + _EXT[fmt])
            prev_gui = read_gui_document_xml(path)  # камеру прежнего файла берём ДО удаления
            _fresh(path)
            doc.saveAs(path)
            mode = inject_camera(path, parts, prev_gui)
            if mode:
                kind = "сохранён прежний ракурс" if mode == "reused" else "пресет-изометрия"
                App.Console.PrintMessage(f"[export] стартовая камера: {kind}\n")
            written.append(path)
            App.Console.PrintMessage(f"[export] FCStd → {path}\n")
            continue
        # STL/STEP — по файлу на деталь.
        for name, feature in parts:
            suffix = f"_{name.lower()}" if multi else ""
            path = os.path.join(output.directory, output.name + suffix + _EXT[fmt])
            _fresh(path)
            if fmt == "STEP":
                feature.Shape.exportStep(path)
            else:
                _write_stl(feature.Shape, path, output)
            written.append(path)
            App.Console.PrintMessage(f"[export] {fmt} {name} → {path}\n")

    return written


def _write_stl(shape, path: str, output: OutputSpec) -> None:
    """Тесселяция формы в меш и запись STL по заданным отклонениям."""
    import MeshPart

    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=output.linear_deflection,
        AngularDeflection=output.angular_deflection,
        Relative=False,
    )
    mesh.write(path)
