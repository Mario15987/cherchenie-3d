"""Множественное выделение и групповые правки, как в КОМПАС-3D (без Qt — проверяется в тестах ядра).

Рамка слева направо (окно) берёт объекты, целиком лежащие внутри; справа налево (секущая) — и те, что пересекают
границу. Элемент библиотеки и прямоугольник — один объект: окно берёт его, только если внутри весь, секущая — если
задета любая часть. Групповые правки работают на месте со списками примитивов.
"""
from __future__ import annotations

import copy
import math

from . import edit2d
from .dims import render
from .geometry import tessellate_arc
from .model import make_dim, make_diadim, make_line, make_raddim, make_text
from .params import EPS, circle_axes, line_angle, line_length, rect_lines, set_param

CURVE = ("line", "circle", "arc")
TAGS = ("blk", "blk_id", "blk_role", "blk_at")


# ---------------------------------------------------------------- рамка
def segments(e: dict) -> list[tuple]:
    """Объект как набор отрезков — для проверки рамкой."""
    t = e["type"]
    if t == "line":
        return [(e["x1"], e["y1"], e["x2"], e["y2"])]
    if t in ("circle", "arc"):
        pts = tessellate_arc({**e, "a0": 0.0, "a1": 0.0} if t == "circle" else e)
        return [(*a, *b) for a, b in zip(pts, pts[1:])] + list(circle_axes(e))
    if t == "hatch":
        out = []
        for poly in e["boundary"]:
            out += [(*a, *b) for a, b in zip(poly, poly[1:] + poly[:1])]
        return out
    d = render(e)
    out = list(d.segs)
    for x, y, h, s, ang, align in d.texts:   # строка надписи — прямоугольник по её габариту
        w = 0.8 * h * len(s)
        dx = {"center": -w / 2, "right": -w}.get(align, 0.0)
        a = math.radians(ang)
        pts = [(x + u * math.cos(a) - v * math.sin(a), y + u * math.sin(a) + v * math.cos(a)) for u, v in ((dx, 0), (dx + w, 0), (dx + w, h), (dx, h))]
        out += [(*p, *q) for p, q in zip(pts, pts[1:] + pts[:1])]
    for tri in d.arrows:
        out += [(*p, *q) for p, q in zip(tri, tri[1:] + tri[:1])]
    return out


def _inside(p, r):
    x0, y0, x1, y1 = r
    return x0 - EPS <= p[0] <= x1 + EPS and y0 - EPS <= p[1] <= y1 + EPS


def _seg_hits_rect(s, r) -> bool:
    """Отрезок задевает прямоугольник (Лянг — Барски)."""
    x1, y1, x2, y2 = s
    if _inside((x1, y1), r) or _inside((x2, y2), r):
        return True
    rx0, ry0, rx1, ry1 = r
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - rx0), (dx, rx1 - x1), (-dy, y1 - ry0), (dy, ry1 - y1)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def in_window(e, r) -> bool:
    return all(_inside(s[:2], r) and _inside(s[2:], r) for s in segments(e))


def crosses(e, r) -> bool:
    return any(_seg_hits_rect(s, r) for s in segments(e))


def box_select(entities, r, crossing: bool) -> list[str]:
    """id объектов в рамке r = (x0, y0, x1, y1). Группы (элемент библиотеки, прямоугольник) — целиком."""
    r = (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
    test = crosses if crossing else in_window
    groups: dict = {}
    for e in entities:
        key = ("blk", e["blk"]) if e.get("blk") else ("rect", e["rect"]) if e.get("rect") and rect_lines(entities, e["id"]) else ("one", e["id"])
        groups.setdefault(key, []).append(e)
    out = []
    for members in groups.values():
        hits = [test(e, r) for e in members]
        if (any(hits) if crossing else all(hits)):
            out += [e["id"] for e in members]
    return out


# ---------------------------------------------------------------- группа
def bounds(ents) -> tuple[float, float, float, float]:
    from .library import bounds as lb

    return lb(ents)


def center(ents):
    x0, y0, x1, y1 = bounds(ents)
    return (x0 + x1) / 2, (y0 + y1) / 2


def move(ents, dx, dy):
    for e in ents:
        edit2d._map_points(e, lambda p: (p[0] + dx, p[1] + dy))
        if e.get("blk_at"):
            e["blk_at"][0] += dx
            e["blk_at"][1] += dy


def rotate(ents, c, deg):
    """Поворот вокруг c против часовой. Надписи поворачиваются, маркировка элементов — остаётся горизонтальной."""
    for e in ents:
        edit2d._rotate(e, c, deg)
        if e["type"] == "text" and e.get("blk_role") != "label":
            e["ang"] = (e.get("ang", 0.0) + deg) % 360
        if e.get("blk_at"):
            r = math.radians(deg)
            x, y = e["blk_at"][0] - c[0], e["blk_at"][1] - c[1]
            e["blk_at"][:3] = [c[0] + x * math.cos(r) - y * math.sin(r), c[1] + x * math.sin(r) + y * math.cos(r), (e["blk_at"][2] + deg) % 360]


def scale(ents, c, k):
    k = float(k)
    if not 1e-3 < k < 1e3:
        raise ValueError("масштаб от 0,001 до 1000")
    for e in ents:
        edit2d._map_points(e, lambda p: (c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k))
        for key in ("r", "h", "off", "rad"):
            if key in e and e["type"] in ("circle", "arc", "diadim", "raddim", "text", "dim", "angdim"):
                e[key] *= k
        if e.get("blk_at"):
            e["blk_at"][3] *= k


def mirror(entities, ids, axis: str):
    """Зеркально на месте относительно вертикали (axis="v") или горизонтали ("h") через центр выделения."""
    sel = [e for e in entities if e["id"] in set(ids)]
    if not sel:
        raise ValueError("ничего не выбрано")
    cx, cy = center(sel)
    p, q = ((cx, cy - 1), (cx, cy + 1)) if axis == "v" else ((cx - 1, cy), (cx + 1, cy))
    edit2d.mirror(entities, ids, p, q, keep=False)


def common(ents, key):
    """Общее значение длины (L) отрезков или диаметра (d) окружностей; None, если у выбранных оно разное."""
    vals = [line_length(e) if key == "length" else 2 * e["r"] for e in ents]
    return vals[0] if vals and max(vals) - min(vals) < 0.005 else None


def set_common(ents, key, value):
    """Одним вводом — у всех: длина отрезков (от начала по своим углам) или диаметр окружностей (центры на месте)."""
    for e in ents:
        set_param(e, key, value)


def straighten(ents, axis: str):
    """Выровнять: отрезки — по горизонтали или вертикали от начала с той же длиной; окружности — центры на одну линию."""
    lines = [e for e in ents if e["type"] == "line"]
    for e in lines:
        a = line_angle(e)
        if axis == "h":
            set_param(e, "angle", 180.0 if 90 < a < 270 else 0.0)
        else:
            set_param(e, "angle", 270.0 if 180 < a < 360 else 90.0)
    rounds = [e for e in ents if e["type"] in ("circle", "arc")]
    if rounds:
        k = "cy" if axis == "h" else "cx"
        for e in rounds[1:]:
            e[k] = rounds[0][k]


# ---------------------------------------------------------------- действия над одним объектом
def split_line(entities, eid) -> list[dict]:
    """Разделить отрезок пополам: вместо него два, общая точка — середина."""
    e = next(x for x in entities if x["id"] == eid)
    mx, my = (e["x1"] + e["x2"]) / 2, (e["y1"] + e["y2"]) / 2
    a = {**make_line(e["x1"], e["y1"], mx, my, e["style"])}
    b = {**make_line(mx, my, e["x2"], e["y2"], e["style"])}
    i = entities.index(e)
    entities[i:i + 1] = [a, b]
    return [a, b]


def perpendicular(entities, eid, length=None) -> dict:
    """Перпендикуляр из середины влево по ходу отрезка; по умолчанию — половина его длины."""
    e = next(x for x in entities if x["id"] == eid)
    L = line_length(e)
    if L < EPS:
        raise ValueError("отрезок нулевой длины")
    k = (length or L / 2) / L
    mx, my = (e["x1"] + e["x2"]) / 2, (e["y1"] + e["y2"]) / 2
    nx, ny = -(e["y2"] - e["y1"]) * k, (e["x2"] - e["x1"]) * k
    p = make_line(mx, my, mx + nx, my + ny, e["style"])
    entities.append(p)
    return p


def dimension_for(project, e) -> dict:
    """Размер на объект — сразу ассоциативный: на отрезок параллельный, на окружность ⌀, на дугу R."""
    if e["type"] == "line":
        off = max(8.0, line_length(e) * 0.1)
        return {**make_dim(e["x1"], e["y1"], e["x2"], e["y2"], off, "aligned"), "refs": [[e["id"], "p1"], [e["id"], "p2"]]}
    if e["type"] == "circle":
        return {**make_diadim(e["cx"], e["cy"], e["r"], 45.0), "ref": e["id"]}
    if e["type"] == "arc":
        mid = e["a0"] + ((e["a1"] - e["a0"]) % 360) / 2
        return {**make_raddim(e["cx"], e["cy"], e["r"], mid), "ref": e["id"]}
    raise ValueError("размер ставится на отрезок, окружность или дугу")


def duplicate(entities, ids, dx=10.0, dy=-10.0) -> list[dict]:
    """Копия выбранного со сдвигом; группы и размеры копии — свои."""
    src = [e for e in entities if e["id"] in set(ids)]
    if not src:
        raise ValueError("ничего не выбрано")
    batch = [edit2d._copy(e) for e in src]
    move(batch, dx, dy)
    edit2d._reblock(batch, src)
    entities.extend(batch)
    return batch


def paste(entities, clip: list[dict], at=None, offset=(10.0, -10.0)) -> list[dict]:
    """Вставить скопированное: левым нижним углом габарита в точку at (или со сдвигом от места копирования)."""
    if not clip:
        raise ValueError("буфер пуст: сначала Ctrl+C")
    batch = [edit2d._copy(e) for e in clip]
    x0, y0, _, _ = bounds(clip)
    dx, dy = (at[0] - x0, at[1] - y0) if at is not None else offset
    move(batch, dx, dy)
    edit2d._reblock(batch, clip)
    entities.extend(batch)
    return batch


def explode_rect(lines) -> None:
    """Разрушить прямоугольник: дальше каждая сторона — обычный отрезок."""
    for e in lines:
        e.pop("rect", None)


def explode_block(entities, inst) -> list[dict]:
    """Разрушить элемент библиотеки на примитивы: остаются отрезки, дуги и надписи без привязки к экземпляру."""
    part = [e for e in entities if e.get("blk") == inst]
    if not part:
        raise ValueError("элемент не найден")
    for e in part:
        for k in TAGS:
            e.pop(k, None)
    return part


def explode_dim(entities, eid) -> list[dict]:
    """Разрушить размер на тонкие отрезки и надписи — он перестаёт быть размером и не следует за геометрией."""
    e = next(x for x in entities if x["id"] == eid)
    d = render(e)
    out = [make_line(*s, "thin") for s in d.segs]
    for tri in d.arrows:
        out += [make_line(*p, *q, "thin") for p, q in zip(tri, tri[1:] + tri[:1])]
    out += [make_text(x, y, s, h, ang, align) for x, y, h, s, ang, align in d.texts]
    i = entities.index(e)
    entities[i:i + 1] = out
    return out


def block_anchor(part) -> tuple[float, float]:
    """Точка вставки элемента (у старых проектов — центр габарита)."""
    for e in part:
        if e.get("blk_at"):
            return e["blk_at"][0], e["blk_at"][1]
    return center(part)


def clip_copy(entities, ids) -> list[dict]:
    return copy.deepcopy([e for e in entities if e["id"] in set(ids)])

