#!/usr/bin/env python
"""Точка входа генератора подставки для свёрел (Composition Root).

Связывает слои воедино: загрузка конфига → (опц. GUI-диалог) → разрешение плана →
построение геометрии → экспорт. Это единственное место, знающее обо всех слоях сразу.

Запуск (по умолчанию открывается диалог правки):
  с диалогом:  ./drill-holder [путь/к/holder_config.py]   (freecadcmd поднимет своё Qt-окно)
  headless:    ./drill-holder --no-gui [путь]              (сразу по конфигу, без диалога)
  как макрос:  открыть в FreeCAD (Macro) и запустить — диалог появится в окне FreeCAD.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Чтобы `import drillholder` работал при запуске файла напрямую (freecadcmd/макрос).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from drillholder.config import ConfigError, build_specs, load_raw_config  # noqa: E402
from drillholder.layout import resolve_plan  # noqa: E402

# Признак того, что мы сами подняли QApplication в headless (см. _is_entry_script внизу).
_HEADLESS_QT_USED = False


def _say(msg: str, *, warn: bool = False) -> None:
    """Сообщение пользователю. В ``freecadcmd`` обычный ``print()`` в stdout теряется (буфер не
    сбрасывается при выходе), поэтому пишем через консоль FreeCAD, когда она доступна."""
    try:
        import FreeCAD as App
        (App.Console.PrintWarning if warn else App.Console.PrintMessage)(msg + "\n")
    except Exception:  # noqa: BLE001 — вне FreeCAD (обычный python/тесты)
        print(msg, file=sys.stderr if warn else sys.stdout)


class _SayLogHandler(logging.Handler):
    """Маршрутизирует записи логгера ``drillholder`` в консоль: WARNING+ — жёлтым."""

    def emit(self, record: logging.LogRecord) -> None:
        _say(record.getMessage(), warn=record.levelno >= logging.WARNING)


def _setup_logging() -> None:
    """Направить диагностику ядра (напр. авто-уменьшение пружин) в консоль FreeCAD/CLI."""
    logger = logging.getLogger("drillholder")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(h, _SayLogHandler) for h in logger.handlers):
        logger.addHandler(_SayLogHandler())


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Генератор подставки для свёрел (FreeCAD)")
    parser.add_argument(
        "config", nargs="?", default=None,
        help="путь к holder_config.py (по умолчанию рядом со скриптом или в текущем каталоге)",
    )
    parser.add_argument(
        "--no-gui", action="store_true",
        help="собрать без диалога (headless) — сразу по конфигу",
    )
    return parser.parse_args(argv)


def _script_args():
    """Аргументы пользователя без шумовых токенов FreeCAD.

    ``python build_holder.py cfg``            → argv[1:] = ['cfg']
    ``freecadcmd build_holder.py cfg``        → ['build_holder.py', 'cfg']          → ['cfg']
    ``freecadcmd build_holder.py -- a --gui`` → ['build_holder.py','--','a','--gui'] → ['a','--gui']

    freecadcmd сам разбирает опции с ``--`` (--gui приняло бы за свой флаг), поэтому лончер
    ставит разделитель ``--``: всё после него FreeCAD пробрасывает дословно. Снимаем его тут.
    """
    args = list(sys.argv[1:])
    me = os.path.basename(__file__)
    if args and os.path.basename(args[0]) == me:
        args = args[1:]
    if args and args[0] in ("--", "--pass"):
        args = args[1:]
    return args


def _resolve_config_path(args) -> str:
    if args.config:
        return args.config
    local = os.path.join(_HERE, "holder_config.py")
    return local if os.path.isfile(local) else "holder_config.py"


def _gui_is_up() -> bool:
    try:
        import FreeCAD as App
        return bool(getattr(App, "GuiUp", False))
    except Exception:  # noqa: BLE001
        return False


def _want_dialog(args) -> bool:
    """Показывать ли диалог. По умолчанию — да (GUI-режим); ``--no-gui`` собирает сразу по конфигу.

    Даже в headless ``freecadcmd`` поднимает собственное Qt-окно (если есть дисплей); без дисплея
    (CI/offscreen) ``show_dialog`` штатно откатывается на конфиг."""
    return not args.no_gui


def _print_usage_banner() -> None:
    """Краткая шпаргалка по ключам запуска — печатается в самом начале каждого запуска.

    Раскрашиваем ANSI-цветом только при выводе в терминал; в файл/пайп — без escape-кодов.
    """
    color = sys.stdout.isatty()
    c_ttl = "\033[1;36m" if color else ""   # жирный голубой — заголовок
    c_key = "\033[1;32m" if color else ""   # жирный зелёный — ключ
    c_dim = "\033[2m" if color else ""      # тусклый — пояснение
    rst = "\033[0m" if color else ""

    rows = [
        ("[config.py]", "путь к конфигу (по умолчанию holder_config.py рядом со скриптом)"),
        ("--no-gui", "собрать сразу по конфигу, без диалога (для скриптов/headless)"),
    ]
    lines = [f"{c_ttl}drill-holder — подставка для свёрел.{rst} "
             f"{c_dim}По умолчанию открывается диалог правки; ключи запуска:{rst}"]
    for key, desc in rows:
        lines.append(f"  {c_key}{key:<13}{rst} {c_dim}{desc}{rst}")
    _say("\n".join(lines))
    _flush_streams()  # stdout буферизуется — сбрасываем, чтобы баннер реально был первым


def main(argv=None) -> int:
    _print_usage_banner()
    _setup_logging()
    args = _parse_args(_script_args() if argv is None else argv)
    path = _resolve_config_path(args)

    try:
        raw = load_raw_config(path)
    except ConfigError as exc:
        _say(f"Ошибка конфига: {exc}", warn=True)
        return 2

    # Диалог по умолчанию (кроме --no-gui): в работающем GUI FreeCAD или в headless, где мы сами
    # поднимаем QApplication. Если PySide/дисплей недоступен — тихо откатываемся на конфиг.
    if _want_dialog(args):
        if not _gui_is_up():
            global _HEADLESS_QT_USED
            _HEADLESS_QT_USED = True  # свой Qt в headless → особый выход (см. _is_entry_script)
        try:
            from drillholder.gui import show_dialog
            edited = show_dialog(raw, path)
            if edited is None:
                _say("Диалог отменён — сборка не выполнена.")
                return 0
            raw = edited
        except Exception as exc:  # noqa: BLE001 — нет PySide/диалог не открылся → конфиг как есть
            _say(f"GUI-диалог недоступен ({exc}); использую конфиг.", warn=True)

    try:
        drills, specs = build_specs(raw)
    except ConfigError as exc:
        _say(f"Ошибка конфига: {exc}", warn=True)
        return 2

    plan = resolve_plan(drills, specs)
    _say(f"Свёрел: {len(plan.sockets)}; режим раскладки: {plan.resolved_mode.value}")

    # Геометрия и экспорт импортируются здесь: ядро (config/layout) работает без FreeCAD,
    # а эти слои требуют FreeCAD — держим импорт ленивым, ближе к использованию.
    from drillholder.geometry import build_model
    from drillholder.export import export_model

    doc, parts = build_model(plan)
    paths = export_model(doc, parts, specs.output)
    _say("Готово. Файлы:")
    for p in paths:
        _say(f"  {p}")
    return 0


def _is_entry_script() -> bool:
    """True, если файл запущен как точка входа — обычным Python или через freecadcmd.

    freecadcmd выполняет файл с ``__name__`` == имя файла (не "__main__") и кладёт путь
    скрипта в ``argv[1]``; распознаём этот случай, чтобы не запускать main() при импорте.
    """
    if __name__ == "__main__":
        return True
    argv0 = os.path.basename(sys.argv[0]).lower() if sys.argv else ""
    is_freecad = argv0 in ("freecadcmd", "freecad", "freecadcmd.exe", "freecad.exe")
    same_file = len(sys.argv) > 1 and os.path.basename(sys.argv[1]) == os.path.basename(__file__)
    return is_freecad and same_file


def _flush_streams() -> None:
    """Сбросить и Python-, и C-уровневые буферы вывода.

    Консоль FreeCAD пишет через C++ stdio, чей буфер ``os._exit`` не сбрасывает; зовём
    libc ``fflush(NULL)`` через ctypes, иначе хвост вывода («Готово. Файлы:») теряется.
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes
        ctypes.CDLL(None).fflush(None)
    except Exception:  # noqa: BLE001 — ctypes/libc недоступны: довольствуемся Python-flush
        pass


if _is_entry_script():
    _rc = main()
    _flush_streams()
    if _HEADLESS_QT_USED:
        # Свой QApplication в headless ломает глобальный teardown FreeCAD при штатном выходе
        # (libc++abi: recursive_mutex lock failed). Файлы уже записаны — выходим немедленно,
        # минуя сбойную очистку. os._exit не зовёт atexit/деструкторы, поэтому flush сделали выше.
        os._exit(_rc)
    sys.exit(_rc)
