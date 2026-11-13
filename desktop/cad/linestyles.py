"""Типы линий по ГОСТ 2.303-68: толщина, штрихи и пробелы (мм), волнистая линия."""
from __future__ import annotations

import math

S = 0.5  # толщина основной линии s, мм

# толщина (мм) и рисунок «штрих, пробел, ...» (мм); пустой — сплошная
STYLE_SPEC = {
    "main": (S, []),
    "thin": (S / 3, []),
    "hidden": (S / 2, [6.0, 2.0]),                       # штриховая: штрихи 2–8, промежутки 1–2
    "axis": (S / 3, [15.0, 3.0, 0.5, 3.0]),              # штрихпунктирная тонкая: штрихи 5–30, промежутки 3–5
    "fold": (S / 2, [15.0, 4.0, 0.5, 4.0, 0.5, 4.0]),    # с двумя точками: промежутки 4–6
    "wavy": (S / 3, []),                                 # волнистая — сплошная, форму задаёт wavy_points
}

DXF_LTYPE = {"main": "CONTINUOUS", "thin": "CONTINUOUS", "hidden": "HIDDEN", "axis": "CENTER", "fold": "PHANTOM", "wavy": "CONTINUOUS"}


def wavy_points(x1, y1, x2, y2, amp=1.0, wave=8.0) -> list[tuple[float, float]]:
    """Волнистая линия обрыва: синусоида вдоль отрезка, концы — на самом отрезке."""
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1e-9:
        return [(x1, y1), (x2, y2)]
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    n = max(8, int(L / wave * 12))
    waves = max(1, round(L / wave))
    return [(x1 + ux * L * i / n - uy * amp * math.sin(2 * math.pi * waves * i / n),
             y1 + uy * L * i / n + ux * amp * math.sin(2 * math.pi * waves * i / n)) for i in range(n + 1)]
