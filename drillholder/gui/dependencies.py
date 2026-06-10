"""Движок зависимостей формы — применимость, валидность и финальная проверка. Без Qt.

Три обязанности (все читают «сырой» конфиг-dict, как его собирает форма):
  * :func:`disabled_fields` — какие поля **неприменимы** при текущих значениях соседей
    (их виджеты дизейблятся) и почему. Правила срисованы с применимости параметров в
    :mod:`drillholder.config.validate` (что игнорируется при каком mode/флаге).
  * :func:`invalid_fields` — какие поля содержат **недопустимое** значение (подсветка + совет).
    Это дешёвые межполевые числовые инварианты; тексты совета взяты дословно из ``validate``.
  * :func:`run_validation` — финальный привратник: гоняет ``build_specs`` (та же проверка, что
    при сборке) и собирает WARNING'и мягкой авто-коррекции пружин для нейтрального показа.

Модуль чистый: тестируется обычным ``python3`` без Qt и без FreeCAD.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..config import ConfigError, build_specs

# (section, key) → причина неприменимости. Возвращается только для дизейбленных полей.
Disabled = Dict[Tuple[str, str], str]
# (section, key) → сообщение «почему невалидно + совет».
Invalid = Dict[Tuple[str, str], str]

_LID_BASE = ("wall", "clearance", "top_gap", "skirt")  # есть у любой крышки (mode != none)
_LID_REMOVABLE = ("snap", "snap_protrusion")
_LID_HINGED = ("pin_diameter", "pin_length", "ear_thickness", "hinge_clearance")
_SPRING_BODY = (
    "count", "rows", "leaf_width", "leaf_length", "leaf_thickness",
    "slot_width", "relief_gap", "bump_protrusion", "bump_radius",
)
_LABEL_BODY = ("mode", "position", "reference", "size", "depth", "font", "offset", "multicolor")
_RING_BODY = ("width", "depth", "gap")
_DRILL_GEOMETRY_BODY = ("style", "flutes", "helix_angle_deg", "point_angle_deg", "flute_depth_ratio")
_DRILL_SPIRAL_ONLY = ("flutes", "helix_angle_deg", "flute_depth_ratio")  # неприменимы для cylinder


def _g(cfg: Dict[str, Any], section: str, key: str) -> Any:
    return cfg.get(section, {}).get(key)


def disabled_fields(cfg: Dict[str, Any]) -> Disabled:
    """Вернуть поля, неприменимые при текущих значениях, с причиной для tooltip.

    Поле остаётся в конфиге со своим значением (его проигнорирует ``validate`` по mode) —
    дизейбл лишь сообщает, что сейчас оно ни на что не влияет.
    """
    out: Disabled = {}
    layout_mode = str(_g(cfg, "layout", "mode")).lower()
    lid_mode = str(_g(cfg, "lid", "mode")).lower()
    foot_mode = str(_g(cfg, "foot", "mode")).lower()

    # ── Раскладка ────────────────────────────────────────────────────────────
    # align применяется и к row, и к grid (внутри каждого ряда), поэтому не дизейблим его.
    if layout_mode != "grid":
        out[("layout", "grid_cols")] = "Число столбцов задаётся только для раскладки grid."
        out[("layout", "row_gap")] = "Зазор между рядами задаётся только для раскладки grid."
        out[("layout", "serpentine")] = "Раскладка «змейкой» применяется только для раскладки grid."
    if layout_mode != "angled":
        out[("layout", "angle_deg")] = "Угол наклона применяется только для раскладки angled."

    # ── Крышка ───────────────────────────────────────────────────────────────
    # Селектор lid.mode оставляем активным (чтобы можно было выставить none и снять конфликт
    # с angled), а вот его подполя дизейблим по mode и по запрету для angled.
    if layout_mode == "angled":
        for key in _LID_BASE + _LID_REMOVABLE + _LID_HINGED:
            out[("lid", key)] = "Крышка не поддерживается для наклонной раскладки (angled)."
    else:
        if lid_mode == "none":
            for key in _LID_BASE + _LID_REMOVABLE + _LID_HINGED:
                out[("lid", key)] = 'Выберите режим крышки (removable/hinged), чтобы задать её параметры.'
        else:
            if lid_mode != "removable":
                for key in _LID_REMOVABLE:
                    out[("lid", key)] = "Защёлка применяется только для съёмной крышки (removable)."
            if lid_mode != "hinged":
                for key in _LID_HINGED:
                    out[("lid", key)] = "Ось/ушко применяются только для откидной крышки (hinged)."

    # ── Основание ────────────────────────────────────────────────────────────
    if foot_mode == "none":
        for key in ("thickness", "margin", "min_margin", "tip_angle_deg", "chamfer"):
            out[("foot", key)] = "Выберите режим основания (manual/auto), чтобы задать его параметры."
    else:
        if foot_mode != "manual":
            out[("foot", "margin")] = "Ручной вынос задаётся только при режиме основания manual."
        if foot_mode != "auto":
            for key in ("min_margin", "tip_angle_deg"):
                out[("foot", key)] = "Параметр применяется только при режиме основания auto."

    # ── Пружины / подписи (групповые флаги) ──────────────────────────────────
    if not bool(_g(cfg, "springs", "enabled")):
        for key in _SPRING_BODY:
            out[("springs", key)] = "Включите пружины-детенты, чтобы задать их параметры."
    if not bool(_g(cfg, "labels", "enabled")):
        for key in _LABEL_BODY:
            out[("labels", key)] = "Включите гравировку подписей, чтобы задать их параметры."
    if not bool(_g(cfg, "rings", "enabled")):
        for key in _RING_BODY:
            out[("rings", key)] = "Включите колечки вокруг гнёзд, чтобы задать их параметры."
    if not bool(_g(cfg, "drill_geometry", "enabled")):
        for key in _DRILL_GEOMETRY_BODY:
            out[("drill_geometry", key)] = "Включите генерацию моделей свёрел, чтобы задать их параметры."
    elif str(_g(cfg, "drill_geometry", "style")).lower() != "spiral":
        for key in _DRILL_SPIRAL_ONLY:
            out[("drill_geometry", key)] = "Параметры канавок применяются только для формы «spiral»."
    return out


def invalid_fields(cfg: Dict[str, Any]) -> Invalid:
    """Дешёвые межполевые числовые инварианты для пер-польной подсветки.

    Полную проверку даёт :func:`run_validation`; здесь — лишь те правила, чьё сообщение
    указывает конкретные поля, чтобы подсветить именно их (рамкой). Тексты — как в ``validate``.
    """
    out: Invalid = {}

    def num(section: str, key: str) -> Optional[float]:
        try:
            return float(_g(cfg, section, key))
        except (TypeError, ValueError):
            return None

    mn, mx = num("socket", "min_depth"), num("socket", "max_depth")
    if mn is not None and mx is not None and mx < mn:
        msg = f"socket.max_depth ({mx:g}) должно быть >= socket.min_depth ({mn:g})."
        out[("socket", "max_depth")] = msg
        out[("socket", "min_depth")] = msg

    if bool(_g(cfg, "springs", "enabled")):
        prot, rad = num("springs", "bump_protrusion"), num("springs", "bump_radius")
        if prot is not None and rad is not None and rad < prot / 2.0:
            msg = (
                f"springs.bump_radius ({rad:g}) должно быть >= bump_protrusion/2 ({prot / 2.0:g}), "
                "иначе детент не приваривается к лепестку."
            )
            out[("springs", "bump_radius")] = msg

    if str(_g(cfg, "layout", "mode")).lower() == "angled":
        angle = num("layout", "angle_deg")
        if angle is not None and not 0 < angle < 90:
            out[("layout", "angle_deg")] = (
                f"layout.angle_deg: для angled нужно в (0, 90), получено {angle:g}."
            )

    if str(_g(cfg, "foot", "mode")).lower() == "auto":
        tip = num("foot", "tip_angle_deg")
        if tip is not None and not 0 < tip < 45:
            out[("foot", "tip_angle_deg")] = (
                f"foot.tip_angle_deg: нужно в (0, 45), получено {tip:g}."
            )
    return out


class _CollectHandler(logging.Handler):
    """Перехватывает WARNING+ из логгера drillholder во время одной валидации."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def run_validation(cfg: Dict[str, Any]) -> Tuple[Optional[str], List[str]]:
    """Прогнать ``build_specs`` (как при сборке) и вернуть ``(ошибка|None, предупреждения)``.

    ``ошибка`` — текст :class:`ConfigError` (причина + совет), при котором сборку нужно
    блокировать. ``предупреждения`` — нейтральные WARNING'и мягкой авто-коррекции из логгера
    (напр. длина свёрл, ряды детентов крышки), которые стоит показать, но не пугать. Подгонка
    пружин теперь пер-гнездовая и штатная (``layout.fit_springs``) — она предупреждений не шлёт.
    """
    logger = logging.getLogger("drillholder")
    handler = _CollectHandler()
    logger.addHandler(handler)
    error: Optional[str] = None
    try:
        build_specs(cfg)
    except ConfigError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 — в GUI любой сбой проверки = блокирующая ошибка
        error = str(exc)
    finally:
        logger.removeHandler(handler)
    # При ошибке предупреждения авто-коррекции не показываем — они уже неактуальны.
    warnings = [] if error else handler.messages
    return error, warnings
