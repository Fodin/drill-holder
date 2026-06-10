"""Подбор TTF/OTF-шрифта для подписей — чистый модуль (без FreeCAD), тестируется отдельно.

``labels.font`` может быть:
  * путём к файлу .ttf/.otf — используется как есть;
  * именем системного шрифта («Arial», «DejaVu Sans») — ищется файл в типовых каталогах;
  * пустым — берётся первый доступный системный шрифт (нормальное «авто», не ошибка).
В крайнем случае (ничего не найдено) — первый попавшийся .ttf/.otf в каталогах, иначе ``None``.
"""

from __future__ import annotations

import os
from typing import Dict, NamedTuple, Optional

# Кандидаты по приоритету для разных ОС (macOS / Linux / Windows / WSL).
FALLBACK_FONTS = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Verdana.ttf",
    # Linux (Debian/Ubuntu, Fedora, Arch)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    # Windows / WSL
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
    "/mnt/c/Windows/Fonts/arial.ttf",
]

# Каталоги для поиска по имени семейства и «хоть какого-нибудь» шрифта.
FONT_DIRS = [
    "/System/Library/Fonts",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    "C:\\Windows\\Fonts",
    "/mnt/c/Windows/Fonts",
]

_FONT_EXTS = (".ttf", ".otf")
# Маркеры начертаний — при поиске по семейству предпочитаем обычное (regular) этим вариантам.
_STYLE_HINTS = ("bold", "italic", "oblique", "light", "thin", "medium", "black", "semibold", "condensed")


class FontResult(NamedTuple):
    """Итог подбора: путь к файлу (или ``None``) и был ли выполнен запрос пользователя.

    ``honored`` = True, когда нашли именно запрошенный файл/семейство, либо запрос был пуст
    (пустой = осознанное «авто», не повод для предупреждения). False — когда запрошенный
    шрифт не найден и пришлось взять запасной.
    """

    path: Optional[str]
    honored: bool


_cache: Dict[str, FontResult] = {}


def _norm(s: str) -> str:
    """Нормализовать имя для сравнения: только буквы/цифры в нижнем регистре."""
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _find_by_family(name: str) -> Optional[str]:
    """Найти файл шрифта по имени семейства («DejaVu Sans» → DejaVuSans.ttf).

    Сравниваем нормализованное имя файла с нормализованным семейством; среди совпадений
    предпочитаем обычное начертание (точное совпадение / regular) полужирному/курсиву и т.п.
    """
    target = _norm(name)
    if not target:
        return None
    best: Optional[str] = None
    best_rank = 99
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in sorted(files):
                if not fn.lower().endswith(_FONT_EXTS):
                    continue
                stem = _norm(os.path.splitext(fn)[0])
                if not stem.startswith(target):
                    continue
                extra = stem[len(target):]
                if extra == "":
                    return os.path.join(root, fn)  # точное совпадение — лучше не найти
                if "regular" in extra:
                    rank = 1
                elif any(h in extra for h in _STYLE_HINTS):
                    rank = 3
                else:
                    rank = 2
                if rank < best_rank:
                    best, best_rank = os.path.join(root, fn), rank
    return best


def _scan_dirs() -> Optional[str]:
    """Первый .ttf/.otf в типовых каталогах (детерминированно — по сортировке)."""
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in sorted(files):
                if fn.lower().endswith(_FONT_EXTS):
                    return os.path.join(root, fn)
    return None


def resolve_font_detailed(preferred: str = "") -> FontResult:
    """Подобрать шрифт, вернув путь и признак выполнения запроса (см. :class:`FontResult`)."""
    key = preferred or ""
    if key in _cache:
        return _cache[key]

    # 1) Явный путь к файлу.
    if preferred and os.path.isfile(preferred):
        result = FontResult(preferred, True)
    # 2) Имя системного семейства.
    elif preferred and (fam := _find_by_family(preferred)) is not None:
        result = FontResult(fam, True)
    else:
        # 3) Запасной: список типовых, затем скан каталогов. honored=True только если запрос
        #    был пуст (это и есть штатное «авто»), иначе запрошенное не нашли → honored=False.
        honored = not preferred
        path = next((p for p in FALLBACK_FONTS if os.path.isfile(p)), None) or _scan_dirs()
        result = FontResult(path, honored)

    _cache[key] = result
    return result


def resolve_font(preferred: str = "") -> Optional[str]:
    """Вернуть путь к шрифту: заданный/системный (если найден), иначе запасной, иначе ``None``."""
    return resolve_font_detailed(preferred).path
