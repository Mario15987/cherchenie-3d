"""Размеры и обозначения по ГОСТ 2.307 / 2.309: геометрия для экрана, DXF и SVG, текст с допуском, выбор щелчком.

render(e) -> Drawn: отрезки (тонкие линии), закрашенные стрелки, надписи. Один код для всех выводов.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

ARROW_L, ARROW_W = 3.0, 0.5   # стрелка: длина и полуширина, мм
TEXT_H = 3.5                  # высота размерного числа, мм
EXT = 2.0                     # выход выносной линии за размерную, мм


@dataclass
class Drawn:
    segs: list = field(default_factory=list)     # (x1, y1, x2, y2)
    arrows: list = field(default_factory=list)   # [(x, y) ×3] закрашенный треугольник
    texts: list = field(default_factory=list)    # (x, y, высота, текст, угол°, выравнивание)


def fmt_num(v: float) -> str:
    """Размерное число по ГОСТ: десятичная запятая, без лишних нулей."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


# Поле допуска по ГОСТ 25346 (ISO 286): основное отклонение и квалитет 01, 0…18. H — отверстие, h — вал.
_FIELD = r"(?i:zc|zb|za|cd|ef|fg|js|[a-hjkmnpr-vx-z])(?:01|1[0-8]|[0-9])"
TOL_RE = re.compile(rf"^\s*(±\s*[\d.,]+|[+-][\d.,]+\s*/?\s*[+-][\d.,]+|{_FIELD}(\s*/\s*{_FIELD})?)\s*$")


def check_tolerance(tol: str) -> str:
    """Допуск: «±0,1», «+0,2/-0,1», квалитет «H7» или посадка «H7/g6». Пустая строка — без допуска."""
    t = (tol or "").strip()
    if t and not TOL_RE.match(t):
        raise ValueError("допуск: ±0,1 · +0,2/-0,1 · H7 · H7/g6")
    return t.replace(".", ",")


def dim_text(e: dict, value: float, prefix: str = "") -> str:
    if e.get("text"):
        return e["text"]
    s = prefix + fmt_num(value)
    tol = e.get("tol", "")
    if not tol:
        return s
    if tol.startswith("±"):
        return s + tol.replace(" ", "")
    if tol[0] in "+-":
        return f"{s} ({tol.replace(' ', '')})"
    return s + tol.replace(" ", "")


def _arrow(tip, toward):
    """Стрелка с остриём в tip, направленная от toward к tip."""
    dx, dy = tip[0] - toward[0], tip[1] - toward[1]
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    bx, by = tip[0] - ux * ARROW_L, tip[1] - uy * ARROW_L
    return [tip, (bx - uy * ARROW_W, by + ux * ARROW_W), (bx + uy * ARROW_W, by - ux * ARROW_W)]


def _upright(ang):
    """Угол надписи так, чтобы текст читался снизу или справа (ГОСТ 2.307)."""
    ang %= 360
    return ang - 180 if 90 < ang <= 270 else ang


def text_width(s: str, h: float = TEXT_H) -> float:
    return 0.62 * h * len(s)


def linear_value(e) -> float:
    """Размерное число линейного размера; k — множитель натуральной величины (вид в масштабе 1:2 → k = 2)."""
    k = e.get("k", 1.0)
    if e["kind"] == "horizontal":
        return abs(e["x2"] - e["x1"]) * k
    if e["kind"] == "vertical":
        return abs(e["y2"] - e["y1"]) * k
    return math.hypot(e["x2"] - e["x1"], e["y2"] - e["y1"]) * k


def render(e: dict) -> Drawn:
    t = e["type"]
    d = Drawn()
    if t == "dim":
        x1, y1, x2, y2, off = e["x1"], e["y1"], e["x2"], e["y2"], e.get("off", 8.0)
        if e["kind"] == "horizontal":
            ya = y1 + off
            a, b = (x1, ya), (x2, ya)
            sgn = 1 if ya >= max(y1, y2) else -1 if ya <= min(y1, y2) else 1
            d.segs += [(x1, y1, x1, ya + sgn * EXT), (x2, y2, x2, ya + sgn * EXT)]
            ang = 0.0
        elif e["kind"] == "vertical":
            xa = x1 + off
            a, b = (xa, y1), (xa, y2)
            sgn = 1 if xa >= max(x1, x2) else -1
            d.segs += [(x1, y1, xa + sgn * EXT, y1), (x2, y2, xa + sgn * EXT, y2)]
            ang = 90.0
        else:
            L = math.hypot(x2 - x1, y2 - y1) or 1.0
            nx, ny = -(y2 - y1) / L, (x2 - x1) / L
            a, b = (x1 + nx * off, y1 + ny * off), (x2 + nx * off, y2 + ny * off)
            s = EXT if off >= 0 else -EXT
            d.segs += [(x1, y1, a[0] + nx * s, a[1] + ny * s), (x2, y2, b[0] + nx * s, b[1] + ny * s)]
            ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        d.segs.append((*a, *b))
        if math.dist(a, b) > 2 * ARROW_L + 0.5:
            d.arrows += [_arrow(a, b), _arrow(b, a)]
        else:  # мало места — стрелки снаружи
            d.arrows += [_arrow(a, (2 * a[0] - b[0], 2 * a[1] - b[1])), _arrow(b, (2 * b[0] - a[0], 2 * b[1] - a[1]))]
        up = _upright(ang)
        r = math.radians(up)
        mid = ((a[0] + b[0]) / 2 - math.sin(r) * 1.0, (a[1] + b[1]) / 2 + math.cos(r) * 1.0)
        d.texts.append((*mid, TEXT_H, dim_text(e, linear_value(e)), up, "center"))
    elif t in ("diadim", "raddim"):
        cx, cy, r, ang = e["cx"], e["cy"], e["r"], math.radians(e.get("ang", 45))
        u = (math.cos(ang), math.sin(ang))
        text = dim_text(e, (2 * r if t == "diadim" else r) * e.get("k", 1.0), "⌀" if t == "diadim" else "R")
        far = (cx + u[0] * r, cy + u[1] * r)
        shelf = text_width(text) + 2
        end = (far[0] + u[0] * 4, far[1] + u[1] * 4)
        start = (cx - u[0] * r, cy - u[1] * r) if t == "diadim" else (cx, cy)
        d.segs.append((*start, *end))
        d.arrows.append(_arrow(far, (cx, cy)))
        if t == "diadim":
            d.arrows.append(_arrow(start, (cx, cy)))
        sx = 1 if u[0] >= 0 else -1
        d.segs.append((*end, end[0] + sx * shelf, end[1]))   # полка
        d.texts.append((end[0] + sx * shelf / 2, end[1] + 1.0, TEXT_H, text, 0.0, "center"))
    elif t == "angdim":
        cx, cy, rad = e["cx"], e["cy"], e.get("rad", 20)
        a1, a2 = e["a1"], e["a2"]
        sweep = (a2 - a1) % 360 or 360
        n = max(8, int(sweep / 4))
        pts = [(cx + rad * math.cos(math.radians(a1 + sweep * i / n)), cy + rad * math.sin(math.radians(a1 + sweep * i / n))) for i in range(n + 1)]
        d.segs += [(*pts[i], *pts[i + 1]) for i in range(n)]
        for ang, sgn in ((a1, 1), (a2, -1)):
            p = (cx + rad * math.cos(math.radians(ang)), cy + rad * math.sin(math.radians(ang)))
            tng = (-math.sin(math.radians(ang)) * sgn, math.cos(math.radians(ang)) * sgn)
            d.arrows.append(_arrow(p, (p[0] + tng[0] * ARROW_L, p[1] + tng[1] * ARROW_L)))
            d.segs.append((p[0], p[1], p[0] + math.cos(math.radians(ang)) * EXT, p[1] + math.sin(math.radians(ang)) * EXT))
        mid = math.radians(a1 + sweep / 2)
        tp = (cx + (rad + 2.5) * math.cos(mid), cy + (rad + 2.5) * math.sin(mid))
        value = sweep
        text = e.get("text") or (fmt_num(value) + "°" + (e.get("tol") or ""))
        d.texts.append((*tp, TEXT_H, text, _upright(math.degrees(mid) - 90), "center"))
    elif t == "leader":
        x1, y1, x2, y2 = e["x1"], e["y1"], e["x2"], e["y2"]
        sx = 1 if x2 >= x1 else -1
        shelf = text_width(e["text"]) + 2
        d.segs += [(x1, y1, x2, y2), (x2, y2, x2 + sx * shelf, y2)]
        d.arrows.append(_arrow((x1, y1), (x2, y2)))
        d.texts.append((x2 + sx * shelf / 2, y2 + 1.0, TEXT_H, e["text"], 0.0, "center"))
    elif t == "rough":
        # Знак по ГОСТ 2.309: «галочка» 60° высотой h, длинная сторона ~2h, полка над знаком.
        x, y, h = e["x"], e["y"], 5.0
        left = (x - h * math.tan(math.radians(30)), y + h)
        right = (x + 2 * h * math.tan(math.radians(30)), y + 2 * h)
        text = f"{e['param']} {e['value']}"
        shelf = text_width(text, 3.0) + 1
        d.segs += [(x, y, *left), (x, y, *right), (*right, right[0] + shelf, right[1])]
        d.texts.append((right[0] + shelf / 2, right[1] + 1.0, 3.0, text, 0.0, "center"))
    elif t == "text":
        d.texts.append((e["x"], e["y"], e["h"], e["text"], e.get("ang", 0.0), e.get("align", "left")))
    return d


def pick_distance(e: dict, x: float, y: float) -> float:
    """Расстояние до размера/обозначения для выбора щелчком: по его линиям и надписям."""
    if e["type"] == "hatch":
        from .edit2d import point_in_polygon

        b = e["boundary"]
        inside = point_in_polygon((x, y), b[0]) and not any(point_in_polygon((x, y), h) for h in b[1:])
        return 0.5 if inside else math.inf
    dr = render(e)
    best = math.inf
    for x1, y1, x2, y2 in dr.segs:
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
    for tx, ty, h, s, ang, align in dr.texts:
        # в систему надписи: поворот вокруг точки привязки, затем сдвиг к середине строки по выравниванию
        a = math.radians(-ang)
        lx = (x - tx) * math.cos(a) - (y - ty) * math.sin(a)
        ly = (x - tx) * math.sin(a) + (y - ty) * math.cos(a)
        w = text_width(s, h)
        lx -= {"left": w / 2, "right": -w / 2}.get(align, 0.0)
        best = min(best, max(abs(lx) - w / 2, abs(ly - h / 2) - h / 2, 0.0))
    return best
