"""Параметры геометрии как в КОМПАС-3D: длина и угол отрезка, диаметр и радиус окружности, габарит прямоугольника,
ассоциативные (управляющие) размеры.

Отрезок: длина L меняется от начальной точки вдоль текущего угла (X2 = X1 + L·cos α), угол — поворот вокруг начала.
Прямоугольник — четыре отрезка с общим "rect"; правится как один объект, левый нижний угол на месте.
Размер помнит, к каким точкам он привязан ("refs" — [id, ключ точки], у ⌀/R — "ref" на окружность или дугу):
после любой правки геометрии sync_dims двигает размер за ней, а drive_dim по новому значению размера меняет геометрию.
"""
from __future__ import annotations

import math

EPS = 1e-6
LINEAR = ("dim",)
RADIAL = ("diadim", "raddim")


# ---------------------------------------------------------------- отрезок, окружность, дуга
def line_length(e) -> float:
    return math.hypot(e["x2"] - e["x1"], e["y2"] - e["y1"])


def line_angle(e) -> float:
    """Угол наклона α от оси X против часовой, 0…360°."""
    return math.degrees(math.atan2(e["y2"] - e["y1"], e["x2"] - e["x1"])) % 360.0


def _positive(v, what):
    v = float(v)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{what} должен быть больше нуля")
    return v


def set_param(e: dict, key: str, value) -> None:
    """Изменить параметр объекта по-кадровски. key: length, angle, d, r, x1…, cx…, a0, a1 и прочие числа."""
    t = e["type"]
    v = float(value)
    if not math.isfinite(v):
        raise ValueError("значение — не число")
    if t == "line" and key == "length":
        L = _positive(v, "длина отрезка")
        a = math.radians(line_angle(e)) if line_length(e) > EPS else 0.0
        e["x2"], e["y2"] = e["x1"] + L * math.cos(a), e["y1"] + L * math.sin(a)
    elif t == "line" and key == "angle":
        L, a = line_length(e), math.radians(v)
        e["x2"], e["y2"] = e["x1"] + L * math.cos(a), e["y1"] + L * math.sin(a)
    elif t in ("circle", "arc") and key == "d":
        e["r"] = _positive(v, "диаметр") / 2
    elif t in ("circle", "arc") and key == "r":
        e["r"] = _positive(v, "радиус")
    elif t == "arc" and key in ("a0", "a1"):
        e[key] = v % 360.0
    elif key in e and isinstance(e[key], (int, float)) and not isinstance(e[key], bool):
        if key in ("h", "step") and v <= 0:
            raise ValueError("значение должно быть больше нуля")
        e[key] = v
    else:
        raise ValueError(f"у объекта {t} нет параметра {key}")


def circle_axes(e: dict, over: float = 3.0) -> list[tuple]:
    """Центровые линии окружности с галочкой «Осевые линии»: выходят за контур на 3 мм (ГОСТ 2.303 — 2…5 мм)."""
    if e.get("type") not in ("circle", "arc") or not e.get("axes"):
        return []
    cx, cy, r = e["cx"], e["cy"], e["r"] + over
    return [(cx - r, cy, cx + r, cy), (cx, cy - r, cx, cy + r)]


# ---------------------------------------------------------------- прямоугольник
def rect_lines(entities, eid) -> list[dict] | None:
    """Четыре стороны прямоугольника, в который входит eid, — если он ещё прямоугольник (после усечения — нет)."""
    e = next((x for x in entities if x["id"] == eid), None)
    if e is None or not e.get("rect") or e["type"] != "line":
        return None
    lines = [x for x in entities if x.get("rect") == e["rect"] and x["type"] == "line"]
    return lines if len(lines) == 4 and rect_info(lines) is not None else None


def rect_info(lines) -> tuple[float, float, float, float] | None:
    """(x, y, w, h) — левый нижний угол и стороны, если отрезки образуют замкнутый прямоугольник со сторонами по осям."""
    xs = [v for e in lines for v in (e["x1"], e["x2"])]
    ys = [v for e in lines for v in (e["y1"], e["y2"])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < EPS or y1 - y0 < EPS:
        return None
    sides = set()
    for e in lines:
        a, b = (e["x1"], e["y1"]), (e["x2"], e["y2"])
        if abs(a[1] - b[1]) < EPS and {round(a[0] - x0, 6), round(b[0] - x0, 6)} == {0.0, round(x1 - x0, 6)}:
            sides.add("bottom" if abs(a[1] - y0) < EPS else "top" if abs(a[1] - y1) < EPS else "?")
        elif abs(a[0] - b[0]) < EPS and {round(a[1] - y0, 6), round(b[1] - y0, 6)} == {0.0, round(y1 - y0, 6)}:
            sides.add("left" if abs(a[0] - x0) < EPS else "right" if abs(a[0] - x1) < EPS else "?")
    return (x0, y0, x1 - x0, y1 - y0) if sides == {"bottom", "top", "left", "right"} else None


def set_rect(lines, x, y, w, h) -> None:
    """Перестроить стороны под новый габарит, сохраняя порядок обхода каждой стороны."""
    w, h = _positive(w, "ширина"), _positive(h, "высота")
    x0, y0, _, _ = rect_info(lines)
    for e in lines:
        horiz = abs(e["y1"] - e["y2"]) < EPS
        if horiz:
            y_ = y if abs(e["y1"] - y0) < EPS else y + h
            left_first = e["x1"] <= e["x2"]
            e["x1"], e["x2"] = (x, x + w) if left_first else (x + w, x)
            e["y1"] = e["y2"] = y_
        else:
            x_ = x if abs(e["x1"] - x0) < EPS else x + w
            low_first = e["y1"] <= e["y2"]
            e["y1"], e["y2"] = (y, y + h) if low_first else (y + h, y)
            e["x1"] = e["x2"] = x_


def set_rect_param(lines, key, value) -> None:
    x, y, w, h = rect_info(lines)
    vals = {"x": x, "y": y, "w": w, "h": h}
    if key not in vals:
        raise ValueError(f"у прямоугольника нет параметра {key}")
    vals[key] = float(value)
    set_rect(lines, vals["x"], vals["y"], vals["w"], vals["h"])


# ---------------------------------------------------------------- привязка размеров
def point_of(e: dict, key: str):
    if key == "p1":
        return e["x1"], e["y1"]
    if key == "p2":
        return e["x2"], e["y2"]
    if key == "c":
        return e["cx"], e["cy"]
    if key in ("s", "e") and e["type"] == "arc":
        a = math.radians(e["a0"] if key == "s" else e["a1"])
        return e["cx"] + e["r"] * math.cos(a), e["cy"] + e["r"] * math.sin(a)
    return None


def _set_point(e: dict, key: str, p) -> None:
    if key == "p1":
        e["x1"], e["y1"] = p
    elif key == "p2":
        e["x2"], e["y2"] = p
    elif key == "c":
        e["cx"], e["cy"] = p
    elif key in ("s", "e"):
        e["a0" if key == "s" else "a1"] = math.degrees(math.atan2(p[1] - e["cy"], p[0] - e["cx"])) % 360


def point_ref(entities, x, y):
    """[id, ключ] характерной точки, совпадающей с (x, y): конец отрезка, центр, конец дуги. Иначе None."""
    best = None
    for e in entities:
        t = e.get("type")
        keys = ("p1", "p2") if t == "line" else ("c",) if t == "circle" else ("c", "s", "e") if t == "arc" else ()
        for k in keys:
            p = point_of(e, k)
            if p and math.hypot(p[0] - x, p[1] - y) < 1e-6:
                if best is None or (k != "c" and best[1] == "c"):
                    best = [e["id"], k]
    return best


def attach_dim(project, d: dict, target=None) -> dict:
    """Сделать размер ассоциативным: линейный — к точкам под его концами, ⌀/R — к окружности или дуге с тем же центром."""
    ents = [e for e in project.all_entities() if e.get("type") in ("line", "circle", "arc")]
    if d["type"] in LINEAR:
        r1, r2 = point_ref(ents, d["x1"], d["y1"]), point_ref(ents, d["x2"], d["y2"])
        if r1 and r2:
            d["refs"] = [r1, r2]
    elif d["type"] in RADIAL:
        c = next((e for e in ents if e["type"] in ("circle", "arc") and abs(e["cx"] - d["cx"]) < 1e-6
                  and abs(e["cy"] - d["cy"]) < 1e-6 and abs(e["r"] - d["r"]) < 1e-6), None)
        if c is not None:
            d["ref"] = c["id"]
    return d


def associative(d: dict) -> bool:
    return bool(d.get("refs") or d.get("ref"))


def sync_dims(project) -> int:
    """Размеры следуют за геометрией. Если объект удалён — размер становится свободным. Возвращает число обновлённых."""
    index = {e["id"]: e for e in project.all_entities()}
    n = 0
    for d in list(project.all_entities()):
        if d.get("refs"):
            pts = []
            for eid, key in d["refs"]:
                e = index.get(eid)
                pts.append(point_of(e, key) if e else None)
            if None in pts:
                d.pop("refs")
                continue
            (d["x1"], d["y1"]), (d["x2"], d["y2"]) = pts
            n += 1
        elif d.get("ref"):
            c = index.get(d["ref"])
            if c is None or c["type"] not in ("circle", "arc"):
                d.pop("ref")
                continue
            d["cx"], d["cy"], d["r"] = c["cx"], c["cy"], c["r"]
            n += 1
    return n


def dim_value(d: dict) -> float:
    """Размерное число так, как оно написано на чертеже."""
    from .dims import linear_value

    if d["type"] == "dim":
        return linear_value(d)
    if d["type"] == "diadim":
        return 2 * d["r"] * d.get("k", 1.0)
    if d["type"] == "raddim":
        return d["r"] * d.get("k", 1.0)
    raise ValueError("это не линейный, диаметральный или радиальный размер")


def drive_dim(project, d: dict, value) -> None:
    """Управляющий размер: новое значение меняет геометрию, к которой он привязан. Первая точка размера неподвижна."""
    value = _positive(value, "размер")
    index = {e["id"]: e for e in project.all_entities()}
    k = d.get("k", 1.0) or 1.0
    if d["type"] in RADIAL:
        c = index.get(d.get("ref"))
        if c is None:
            raise ValueError("размер не привязан к окружности — его значение задаёт только текст")
        c["r"] = value / k / (2 if d["type"] == "diadim" else 1)
        sync_dims(project)
        return
    refs = d.get("refs")
    if not refs or any(r[0] not in index for r in refs):
        raise ValueError("размер не привязан к геометрии — его значение задаёт только текст")
    current = dim_value(d) / k
    if current < EPS:
        raise ValueError("нулевой размер нельзя растянуть")
    s = value / k / current
    (id1, k1), (id2, k2) = refs
    a = point_of(index[id1], k1)
    b = point_of(index[id2], k2)
    nb = (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
    e2 = index[id2]
    # обе точки на одном прямоугольнике — меняется его ширина или высота, а не одна сторона
    group = e2.get("rect") if e2.get("rect") and e2.get("rect") == index[id1].get("rect") else None
    lines = rect_lines(list(index.values()), id2) if group else None
    if lines:
        x, y, w, h = rect_info(lines)
        dx, dy = nb[0] - b[0], nb[1] - b[1]
        if abs(dx) > EPS:
            if abs(b[0] - x) < EPS:      # двигается левая сторона
                x, w = x + dx, w - dx
            else:
                w += dx
        if abs(dy) > EPS:
            if abs(b[1] - y) < EPS:
                y, h = y + dy, h - dy
            else:
                h += dy
        set_rect(lines, x, y, w, h)
    elif k2 == "c":                  # центр окружности или дуги — переносится весь объект
        e2["cx"], e2["cy"] = nb
    else:
        _set_point(e2, k2, nb)
    sync_dims(project)


def remap_refs(src: list[dict], copies: list[dict]) -> None:
    """Копии объектов вместе с размерами: размеры копии привязаны к копиям, а не к оригиналам; к чужому — свободны."""
    m = {a["id"]: b["id"] for a, b in zip(src, copies)}
    for c in copies:
        if c.get("refs"):
            if all(r[0] in m for r in c["refs"]):
                c["refs"] = [[m[r[0]], r[1]] for r in c["refs"]]
            else:
                c.pop("refs")
        if c.get("ref"):
            if c["ref"] in m:
                c["ref"] = m[c["ref"]]
            else:
                c.pop("ref")
