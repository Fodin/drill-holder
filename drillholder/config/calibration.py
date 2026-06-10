"""Построение конфига калибровочного купона посадки — чистый слой (без FreeCAD/Qt).

Купон измеряет ИМЕННО ВАШ зазор свободной посадки за одну печать. `socket.clearance` —
глобальный, в одной печати по гнёздам не варьируется; но диаметр бора = ``d + 2·clearance``,
поэтому «разный зазор для одного сверла» кодируется раздутым ``d`` при ``clearance = 0``:

  * пружины ВЫКЛ — калибруем чистую посадку бора (детенты-удержание калибруются отдельно);
  * ``clearance = 0`` — эффективный радиальный зазор гнезда РОВНО равен заложенному в его ``d``;
  * для каждого реального сверла из ``test_drills`` — по гнезду на каждый зазор из ``clearances``.

Подпись гнезда: «<сверло>·<зазор×100>», напр. «3·20» = сверло 3 мм, зазор 0.20 мм на радиус.

Возвращается ЧАСТИЧНЫЙ raw-конфиг (как пользовательский ``CONFIG``): недостающие ключи
дополняются из :data:`DEFAULTS` при слиянии (``load_raw_config``/``deep_merge``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Реальные диаметры свёрел для проверки, мм: проблемный мелкий край + средний.
DEFAULT_TEST_DRILLS: List[float] = [2.0, 3.0, 4.0]
# Радиальные зазоры-кандидаты, мм: 0.20 — типичный FDM-дефолт, шире/уже — разброс под усадку.
DEFAULT_CLEARANCES: List[float] = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]


def calibration_config(
    test_drills: Optional[List[float]] = None,
    clearances: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Вернуть частичный raw-конфиг калибровочного купона (гребёнка гнёзд по зазорам)."""
    test_drills = test_drills or DEFAULT_TEST_DRILLS
    clearances = clearances or DEFAULT_CLEARANCES

    drills = [
        {
            "d": round(d + 2.0 * c, 3),                  # раздутый бор кодирует зазор при clearance=0
            "length": "auto",
            "shank": "round",
            "label": f"{d:g}·{int(round(c * 100))}",   # «3·20» = сверло 3 мм, зазор 0.20
        }
        for d in test_drills
        for c in clearances
    ]

    return {
        "drills": drills,
        "default_shank": "round",
        "socket": {
            "clearance": 0.0,   # 0 → эффективный зазор гнезда РОВНО равен заложенному в его d
            "depth_ratio": 0.30,
            "min_depth": 12.0,  # неглубоко — печатается быстро, но хватает оценить посадку
            "max_depth": 14.0,
        },
        # Пружины выкл: калибруем чистую посадку бора (детенты добавят натяг уже поверх найденного).
        "springs": {"enabled": False},
        "labels": {
            "enabled": True,
            "mode": "engrave",
            "position": "front",
            "size": 3.0,
            "depth": 0.5,
        },
        "layout": {"mode": "grid", "grid_cols": len(clearances), "pitch_extra": 3.0},
        "base": {"floor": 3.0, "min_height": 14.0},
        "output": {"name": "drill_holder_calibration", "formats": ["STL"]},
    }
