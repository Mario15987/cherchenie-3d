"""Типы линий по ГОСТ 2.303-68 (все девять): толщина, штрихи и пробелы (мм), волнистая, с изломами, разомкнутая."""
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
    "axis_thick": (S / 2, [6.0, 3.5, 0.5, 3.5]),         # штрихпунктирная утолщённая: штрихи 3–8, промежутки 3–4
    "open": (S * 1.5, []),                               # разомкнутая: два штриха 8–20 мм по концам, от s до 1,5s
    "zigzag": (S / 3, []),                               # сплошная тонкая с изломами — форму задаёт zigzag_points
}
# Толщина относительно s (ГОСТ 2.303, таблица 1): от и до.
THICKNESS = {"main": (1.0, 1.0), "thin": (1 / 3, 1 / 2), "wavy": (1 / 3, 1 / 2), "hidden": (1 / 3, 1 / 2), "axis": (1 / 3, 1 / 2),
             "axis_thick": (1 / 2, 2 / 3), "open": (1.0, 1.5), "zigzag": (1 / 3, 1 / 2), "fold": (1 / 3, 1 / 2)}
S_MIN, S_MAX = 0.5, 1.4

DXF_LTYPE = {"main": "CONTINUOUS", "thin": "CONTINUOUS", "hidden": "HIDDEN", "axis": "CENTER", "fold": "PHANTOM", "wavy": "CONTINUOUS",
             "axis_thick": "CENTER2", "open": "CONTINUOUS", "zigzag": "CONTINUOUS"}


def zigzag_points(x1, y1, x2, y2, amp=2.0, every=40.0) -> list[tuple[float, float]]:
    """Сплошная тонкая с изломами (длинная линия обрыва): прямая с зигзагами через каждые every мм."""
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 4 * amp:
        return [(x1, y1), (x2, y2)]
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    n = max(1, round(L / every))
    pts = [(x1, y1)]
    for k in range(n):
        c = L * (k + 0.5) / n
        for dt, da in ((-amp, 0.0), (-amp / 2, amp), (amp / 2, -amp), (amp, 0.0)):
            pts.append((x1 + ux * (c + dt) - uy * da, y1 + uy * (c + dt) + ux * da))
    return pts + [(x2, y2)]


def open_parts(x1, y1, x2, y2) -> list[list[tuple[float, float]]]:
    """Разомкнутая линия (положение секущей плоскости): только два штриха по концам, 8–20 мм."""
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1e-9:
        return [[(x1, y1), (x2, y2)]]
    d = min(max(8.0, L * 0.15), 20.0, L / 3)
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    return [[(x1, y1), (x1 + ux * d, y1 + uy * d)], [(x2 - ux * d, y2 - uy * d), (x2, y2)]]


def shaped(style: str, x1, y1, x2, y2) -> list[list[tuple[float, float]]] | None:
    """Ломаные для отрезка, который рисуется не прямой (волнистая, с изломами, разомкнутая); иначе None."""
    if style == "wavy":
        return [wavy_points(x1, y1, x2, y2)]
    if style == "zigzag":
        return [zigzag_points(x1, y1, x2, y2)]
    if style == "open":
        return open_parts(x1, y1, x2, y2)
    return None


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
