"""Редактирование чертежа: усечь, удлинить, фаска, скругление, симметрия, массивы, эквидистанта, штриховка.

Все функции работают со списком примитивов (эскиз или лист) и меняют его на месте. Ошибки — ValueError
с текстом для пользователя.
"""
from __future__ import annotations

import copy
import math

from . import geometry as geo
from .model import CURVES, arc_points, arc_sweep, make_arc, make_line, new_id

EPS = 1e-7


def _find(entities, eid):
    e = next((x for x in entities if x["id"] == eid), None)
    if e is None:
        raise ValueError("объект не найден")
    return e


def _others(entities, e):
    return [x for x in entities if x is not e and x["type"] in CURVES]


def _line_t(e, p):
    dx, dy = e["x2"] - e["x1"], e["y2"] - e["y1"]
    return ((p[0] - e["x1"]) * dx + (p[1] - e["y1"]) * dy) / (dx * dx + dy * dy)


def _ang(e, p):
    return math.degrees(math.atan2(p[1] - e["cy"], p[0] - e["cx"])) % 360.0


def _replace(entities, e, pieces):
    i = entities.index(e)
    entities[i:i + 1] = pieces


# ---------------------------------------------------------------- усечь
def trim(entities, eid, click) -> int:
    """Удаляет участок кривой между ближайшими пересечениями с другими кривыми, на котором щёлкнули.
    Без пересечений кривая удаляется целиком (как в КОМПАС). Возвращает число получившихся частей."""
    e = _find(entities, eid)
    pts = [p for o in _others(entities, e) for p in geo.intersect(e, o)]
    if e["type"] == "line":
        ts = sorted({round(_line_t(e, p), 9) for p in pts if EPS < _line_t(e, p) < 1 - EPS})
        tc = min(max(_line_t(e, click), 0.0), 1.0)
        cuts = [0.0, *ts, 1.0]
        k = next(i for i in range(len(cuts) - 1) if cuts[i] - EPS <= tc <= cuts[i + 1] + EPS)
        P = lambda t: (e["x1"] + t * (e["x2"] - e["x1"]), e["y1"] + t * (e["y2"] - e["y1"]))  # noqa: E731
        pieces = []
        if cuts[k] > EPS:
            pieces.append(make_line(*P(0.0), *P(cuts[k]), e["style"]))
        if cuts[k + 1] < 1 - EPS:
            pieces.append(make_line(*P(cuts[k + 1]), *P(1.0), e["style"]))
        _replace(entities, e, pieces)
        return len(pieces)
    if e["type"] == "circle":
        angs = sorted({round(_ang(e, p), 7) for p in pts})
        if len(angs) < 2:
            _replace(entities, e, [])
            return 0
        ac = _ang(e, click)
        # Участок между соседними пересечениями, содержащий точку щелчка (против часовой стрелки).
        for i, a in enumerate(angs):
            b = angs[(i + 1) % len(angs)]
            if (ac - a) % 360 <= (b - a) % 360:
                _replace(entities, e, [make_arc(e["cx"], e["cy"], e["r"], b, a, e["style"])])
                return 1
        return 1
    # дуга: параметр — угол от начала дуги
    sweep = arc_sweep(e)
    ss = sorted({round((_ang(e, p) - e["a0"]) % 360, 7) for p in pts if EPS < (_ang(e, p) - e["a0"]) % 360 < sweep - EPS})
    sc = (_ang(e, click) - e["a0"]) % 360
    cuts = [0.0, *ss, sweep]
    k = next((i for i in range(len(cuts) - 1) if cuts[i] - EPS <= sc <= cuts[i + 1] + EPS), len(cuts) - 2)
    pieces = []
    if cuts[k] > EPS:
        pieces.append(make_arc(e["cx"], e["cy"], e["r"], e["a0"], e["a0"] + cuts[k], e["style"]))
    if cuts[k + 1] < sweep - EPS:
        pieces.append(make_arc(e["cx"], e["cy"], e["r"], e["a0"] + cuts[k + 1], e["a0"] + sweep, e["style"]))
    _replace(entities, e, pieces)
    return len(pieces)


# ---------------------------------------------------------------- удлинить
def _ray_hits(origin, direction, others):
    """Пересечения луча с кривыми: расстояния вдоль луча > 0."""
    far = (origin[0] + direction[0] * 1e5, origin[1] + direction[1] * 1e5)
    ray = {"type": "line", "x1": origin[0], "y1": origin[1], "x2": far[0], "y2": far[1]}
    out = []
    for o in others:
        for p in geo.intersect(ray, o):
            d = (p[0] - origin[0]) * direction[0] + (p[1] - origin[1]) * direction[1]
            if d > 1e-6:
                out.append((d, p))
    return sorted(out)


def extend(entities, eid, click) -> float:
    """Удлиняет ближний к щелчку конец отрезка (или дуги) до ближайшей кривой. Возвращает прирост длины."""
    e = _find(entities, eid)
    others = _others(entities, e)
    if e["type"] == "line":
        p1, p2 = (e["x1"], e["y1"]), (e["x2"], e["y2"])
        end_is_2 = math.dist(click, p2) < math.dist(click, p1)
        a, b = (p1, p2) if end_is_2 else (p2, p1)
        L = math.dist(a, b)
        d = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        hits = _ray_hits(b, d, others)
        if not hits:
            raise ValueError("на продолжении отрезка нет ни одной кривой")
        dist, p = hits[0]
        if end_is_2:
            e["x2"], e["y2"] = p
        else:
            e["x1"], e["y1"] = p
        return dist
    if e["type"] == "arc":
        s, t = arc_points(e)
        at_end = math.dist(click, t) < math.dist(click, s)
        circle = {"type": "circle", "cx": e["cx"], "cy": e["cy"], "r": e["r"]}
        angs = [_ang(e, p) for o in others for p in geo.intersect(circle, o)]
        if not angs:
            raise ValueError("продолжение дуги не пересекает ни одной кривой")
        if at_end:
            gain = min((a - e["a1"]) % 360 for a in angs if (a - e["a1"]) % 360 > 1e-6)
            e["a1"] = (e["a1"] + gain) % 360
        else:
            gain = min((e["a0"] - a) % 360 for a in angs if (e["a0"] - a) % 360 > 1e-6)
            e["a0"] = (e["a0"] - gain) % 360
        return math.radians(gain) * e["r"]
    raise ValueError("удлинить можно отрезок или дугу")


# ---------------------------------------------------------------- фаска и скругление
def _corner(entities, id1, click1, id2, click2):
    """Угол между двумя отрезками: вершина P и единичные векторы вдоль сохраняемых сторон."""
    l1, l2 = _find(entities, id1), _find(entities, id2)
    if l1["type"] != "line" or l2["type"] != "line" or l1 is l2:
        raise ValueError("выберите два разных отрезка")
    x1, y1, x2, y2 = l1["x1"], l1["y1"], l1["x2"], l1["y2"]
    x3, y3, x4, y4 = l2["x1"], l2["y1"], l2["x2"], l2["y2"]
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-12:
        raise ValueError("отрезки параллельны — угла нет")
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
    P = (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    def side(line, click):
        a, b = (line["x1"], line["y1"]), (line["x2"], line["y2"])
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        s = (click[0] - P[0]) * u[0] + (click[1] - P[1]) * u[1]
        if abs(s) < 1e-9:  # щелчок в вершине — берём дальний конец
            s = max(((q[0] - P[0]) * u[0] + (q[1] - P[1]) * u[1] for q in (a, b)), key=abs)
        return u if s > 0 else (-u[0], -u[1])

    return l1, l2, P, side(l1, click1), side(l2, click2)


def _cut_to(line, P, u, dist):
    """Оставляет у отрезка сторону вдоль u и укорачивает её до точки P + u·dist."""
    ends = [(line["x1"], line["y1"]), (line["x2"], line["y2"])]
    s = [(q[0] - P[0]) * u[0] + (q[1] - P[1]) * u[1] for q in ends]
    far = 0 if s[0] > s[1] else 1
    if s[far] <= dist + 1e-9:
        raise ValueError("фаска или скругление длиннее отрезка")
    q = (P[0] + u[0] * dist, P[1] + u[1] * dist)
    if far == 0:
        line["x2"], line["y2"] = q
    else:
        line["x1"], line["y1"] = q
    return q


def chamfer(entities, id1, click1, id2, click2, d1: float, d2: float | None = None, angle: float | None = None) -> dict:
    """Фаска: по двум катетам (d1, d2) или по катету и углу к первому отрезку. Возвращает отрезок фаски."""
    l1, l2, P, u1, u2 = _corner(entities, id1, click1, id2, click2)
    theta = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
    if angle is not None:
        a = math.radians(angle)
        if not 0 < a < math.pi - theta:
            raise ValueError("угол фаски не подходит для этого угла между отрезками")
        d2 = d1 * math.sin(a) / math.sin(math.pi - theta - a)
    d2 = d1 if d2 is None else d2
    if d1 <= 0 or d2 <= 0:
        raise ValueError("размеры фаски должны быть больше нуля")
    a = _cut_to(l1, P, u1, d1)
    b = _cut_to(l2, P, u2, d2)
    ch = make_line(*a, *b, l1["style"])
    entities.append(ch)
    return ch


def fillet(entities, id1, click1, id2, click2, radius: float) -> dict:
    """Скругление угла дугой радиуса R, касательной к обоим отрезкам. Возвращает дугу."""
    if radius <= 0:
        raise ValueError("радиус должен быть больше нуля")
    l1, l2, P, u1, u2 = _corner(entities, id1, click1, id2, click2)
    cos_t = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    theta = math.acos(cos_t)
    if theta < 1e-6 or theta > math.pi - 1e-6:
        raise ValueError("отрезки лежат на одной прямой")
    t = radius / math.tan(theta / 2)
    bis = (u1[0] + u2[0], u1[1] + u2[1])
    bl = math.hypot(*bis)
    c = (P[0] + bis[0] / bl * radius / math.sin(theta / 2), P[1] + bis[1] / bl * radius / math.sin(theta / 2))
    a = _cut_to(l1, P, u1, t)
    b = _cut_to(l2, P, u2, t)
    a0 = math.degrees(math.atan2(a[1] - c[1], a[0] - c[0]))
    a1 = math.degrees(math.atan2(b[1] - c[1], b[0] - c[0]))
    if (a1 - a0) % 360 > 180:  # дуга скругления всегда меньше 180°
        a0, a1 = a1, a0
    arc = make_arc(c[0], c[1], radius, a0, a1, l1["style"])
    entities.append(arc)
    return arc


# ---------------------------------------------------------------- преобразования
def _map_points(e, f):
    """Применяет преобразование точки f ко всем точкам примитива (на месте)."""
    for kx, ky in (("x1", "y1"), ("x2", "y2"), ("cx", "cy"), ("x", "y")):
        if kx in e:
            e[kx], e[ky] = f((e[kx], e[ky]))
    if e["type"] == "hatch":
        e["boundary"] = [[list(f(tuple(p))) for p in poly] for poly in e["boundary"]]


def _copy(e):
    c = copy.deepcopy(e)
    c["id"] = new_id()
    return c


def _reblock(batch, src=None):
    """Копии элемента библиотеки или прямоугольника — новый экземпляр: своя группа, а не продолжение исходной.
    Размеры копии привязываются к копиям геометрии."""
    fresh = {}
    for c in batch:
        for key in ("blk", "rect"):
            if c.get(key):
                c[key] = fresh.setdefault((key, c[key]), new_id())
    if src is not None:
        from .params import remap_refs

        remap_refs(src, batch)


def mirror(entities, ids, p, q, keep: bool = True) -> list[dict]:
    """Симметрия относительно прямой через p и q. keep=False — переносит, а не копирует."""
    if math.dist(p, q) < 1e-9:
        raise ValueError("ось симметрии задана одной точкой")
    phi = math.atan2(q[1] - p[1], q[0] - p[0])
    c2, s2 = math.cos(2 * phi), math.sin(2 * phi)

    def refl(pt):
        x, y = pt[0] - p[0], pt[1] - p[1]
        return (p[0] + x * c2 + y * s2, p[1] + x * s2 - y * c2)

    out = []
    src = [x for x in entities if x["id"] in set(ids)]
    for e in src:
        m = _copy(e) if keep else e
        _map_points(m, refl)
        deg = math.degrees(phi)
        if m["type"] == "arc":
            m["a0"], m["a1"] = (2 * deg - e["a1"]) % 360, (2 * deg - e["a0"]) % 360
        if m["type"] in ("diadim", "raddim"):
            m["ang"] = (2 * deg - e["ang"]) % 360
        if m["type"] == "angdim":
            m["a1"], m["a2"] = (2 * deg - e["a2"]) % 360, (2 * deg - e["a1"]) % 360
        if keep:
            entities.append(m)
        out.append(m)
    if not out:
        raise ValueError("ничего не выбрано")
    if keep:
        _reblock(out, src)
    return out


def _rotate(e, c, deg):
    r = math.radians(deg)
    cr, sr = math.cos(r), math.sin(r)
    _map_points(e, lambda pt: (c[0] + (pt[0] - c[0]) * cr - (pt[1] - c[1]) * sr, c[1] + (pt[0] - c[0]) * sr + (pt[1] - c[1]) * cr))
    for k in ("a0", "a1", "a2", "ang"):
        if k in e and e["type"] in ("arc", "angdim", "diadim", "raddim"):
            e[k] = (e[k] + deg) % 360


def pattern_linear(entities, ids, nx: int, ny: int, dx: float, dy: float) -> list[dict]:
    """Массив по сетке nx × ny с шагом dx, dy. Исходные объекты — элемент (0, 0)."""
    if nx < 1 or ny < 1 or nx * ny < 2:
        raise ValueError("в массиве должно быть хотя бы два элемента")
    src = [x for x in entities if x["id"] in set(ids)]
    if not src:
        raise ValueError("ничего не выбрано")
    out = []
    for i in range(nx):
        for j in range(ny):
            if i == 0 and j == 0:
                continue
            batch = [_copy(e) for e in src]
            for c in batch:
                _map_points(c, lambda pt, i=i, j=j: (pt[0] + i * dx, pt[1] + j * dy))
            _reblock(batch, src)
            out += batch
    entities.extend(out)
    return out


def pattern_circular(entities, ids, center, count: int, total: float = 360.0) -> list[dict]:
    """Массив по окружности: count элементов на угле total (360° — равномерно по кругу)."""
    if count < 2:
        raise ValueError("в массиве должно быть хотя бы два элемента")
    src = [x for x in entities if x["id"] in set(ids)]
    if not src:
        raise ValueError("ничего не выбрано")
    step = total / count if abs(total - 360) < 1e-9 else total / (count - 1)
    out = []
    for k in range(1, count):
        batch = [_copy(e) for e in src]
        for c in batch:
            _rotate(c, center, k * step)
        _reblock(batch, src)
        out += batch
    entities.extend(out)
    return out


# ---------------------------------------------------------------- эквидистанта
def _loop_of(entities, eid):
    """Замкнутый контур (по порядку обхода), в который входит примитив, — список (id, точки)."""
    segs = geo._segments([e for e in entities if e["type"] in ("line", "arc")])
    adj = {}
    for i, (_, a, b, _) in enumerate(segs):
        adj.setdefault(geo._key(a), []).append(i)
        adj.setdefault(geo._key(b), []).append(i)
    start = next((i for i, s in enumerate(segs) if s[0] == eid), None)
    if start is None:
        return None
    order, cur, at = [], start, geo._key(segs[start][1])
    for _ in range(len(segs)):
        order.append(cur)
        _, a, b, _ = segs[cur]
        at = geo._key(b) if geo._key(a) == at else geo._key(a)
        nxt = [j for j in adj.get(at, []) if j != cur]
        if len(adj.get(at, [])) != 2 or not nxt:
            return None
        cur = nxt[0]
        if cur == start:
            return [segs[i] for i in order]
    return None


def offset(entities, eid, distance: float, side_point, whole_contour: bool = True, style: str | None = None) -> list[dict]:
    """Эквидистанта на расстоянии distance в сторону side_point.
    Отрезок — параллельный отрезок; окружность и дуга — концентрические; замкнутый контур — контур целиком."""
    if distance <= 0:
        raise ValueError("расстояние должно быть больше нуля")
    e = _find(entities, eid)
    st = style or e["style"]
    if e["type"] == "circle" or (e["type"] == "arc" and not whole_contour):
        outside = math.dist(side_point, (e["cx"], e["cy"])) > e["r"]
        r = e["r"] + distance if outside else e["r"] - distance
        if r <= 0:
            raise ValueError("эквидистанта внутрь больше радиуса")
        n = make_arc(e["cx"], e["cy"], r, e["a0"], e["a1"], st) if e["type"] == "arc" else {**_copy(e), "r": r, "style": st}
        entities.append(n)
        return [n]
    loop = _loop_of(entities, eid) if whole_contour else None
    if loop is None:
        if e["type"] != "line":
            raise ValueError("дуга не входит в замкнутый контур")
        L = math.hypot(e["x2"] - e["x1"], e["y2"] - e["y1"])
        nx, ny = -(e["y2"] - e["y1"]) / L, (e["x2"] - e["x1"]) / L
        sgn = 1 if (side_point[0] - e["x1"]) * nx + (side_point[1] - e["y1"]) * ny > 0 else -1
        n = make_line(e["x1"] + sgn * nx * distance, e["y1"] + sgn * ny * distance, e["x2"] + sgn * nx * distance, e["y2"] + sgn * ny * distance, st)
        entities.append(n)
        return [n]
    poly = geo._walk_ordered(loop)
    inside = point_in_polygon(side_point, poly)
    if all(s[0] and next(x for x in entities if x["id"] == s[0])["type"] == "line" for s in loop):
        pts = _offset_polygon_miter(poly, -distance if inside else distance)
    else:
        import manifold3d as m3d
        import numpy as np
        cs = m3d.CrossSection([np.asarray(poly, float)]).offset(-distance if inside else distance, m3d.JoinType.Round, 2.0, 64)
        polys = [np.asarray(p) for p in cs.to_polygons()]
        if not polys:
            raise ValueError("эквидистанта внутрь схлопывает контур")
        pts = [tuple(p) for p in max(polys, key=len)]
    out = [make_line(*pts[i], *pts[(i + 1) % len(pts)], st) for i in range(len(pts))]
    entities.extend(out)
    return out


def _offset_polygon_miter(poly, d):
    """Смещение многоугольника из отрезков: каждая сторона на d наружу (d<0 — внутрь), углы — пересечением сторон."""
    n = len(poly)
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)) / 2
    orient = 1 if area > 0 else -1  # против часовой — внешняя нормаль справа
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = math.dist(a, b)
        nx, ny = (b[1] - a[1]) / L * orient, -(b[0] - a[0]) / L * orient
        lines.append(((a[0] + nx * d, a[1] + ny * d), (b[0] + nx * d, b[1] + ny * d)))
    out = []
    for i in range(n):
        (p1, p2), (p3, p4) = lines[i - 1], lines[i]
        den = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
        if abs(den) < 1e-12:
            out.append(p3)
            continue
        t = ((p1[0] - p3[0]) * (p3[1] - p4[1]) - (p1[1] - p3[1]) * (p3[0] - p4[0])) / den
        out.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))
    return out


# ---------------------------------------------------------------- штриховка
def point_in_polygon(p, poly) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def polygon_area(poly) -> float:
    n = len(poly)
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2


def hatch_region(entities, point):
    """Граница штриховки по точке внутри: наименьший замкнутый контур вокруг точки и контуры-отверстия в нём."""
    polys = geo.contours([e for e in entities if e["type"] in CURVES and e["style"] in ("main", "thin")]).polygons
    around = [p for p in polys if point_in_polygon(point, p)]
    if not around:
        raise ValueError("точка не внутри замкнутого контура")
    outer = min(around, key=polygon_area)
    holes = [p for p in polys if p is not outer and polygon_area(p) < polygon_area(outer)
             and point_in_polygon(p[0], outer) and not point_in_polygon(point, p)]
    # Только прямые отверстия: контур внутри другого отверстия — это «остров», его не вычитаем.
    holes = [h for h in holes if not any(o is not h and point_in_polygon(h[0], o) for o in holes)]
    return [outer, *holes]


def _family(boundary, angle, step, phase=0.0):
    """Семейство параллельных линий под углом, обрезанных по границе (чётно-нечётное правило)."""
    a = math.radians(angle)
    u = (math.cos(a), math.sin(a))      # направление штрихов
    n = (-u[1], u[0])                   # нормаль — по ней идём с шагом
    pts = [p for poly in boundary for p in poly]
    ds = [p[0] * n[0] + p[1] * n[1] for p in pts]
    out = []
    k = math.floor((min(ds) - phase) / step) + 1
    while phase + k * step < max(ds):
        d = phase + k * step
        ts = []
        for poly in boundary:
            m = len(poly)
            for i in range(m):
                p, q = poly[i], poly[(i + 1) % m]
                dp, dq = p[0] * n[0] + p[1] * n[1] - d, q[0] * n[0] + q[1] * n[1] - d
                if (dp > 0) != (dq > 0):
                    s = dp / (dp - dq)
                    x, y = p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])
                    ts.append(x * u[0] + y * u[1])
        ts.sort()
        for i in range(0, len(ts) - 1, 2):
            t0, t1 = ts[i], ts[i + 1]
            out.append((n[0] * d + u[0] * t0, n[1] * d + u[1] * t0, n[0] * d + u[0] * t1, n[1] * d + u[1] * t1))
        k += 1
    return out


def _dashes(segs, dash, gap, offset=0.0):
    out = []
    for x1, y1, x2, y2 in segs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-9:
            continue
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        s = -((x1 * ux + y1 * uy + offset) % (dash + gap))  # фаза от глобальной координаты — штрихи не «плывут»
        while s < L:
            a, b = max(s, 0.0), min(s + dash, L)
            if b > a:
                out.append((x1 + ux * a, y1 + uy * a, x1 + ux * b, y1 + uy * b))
            s += dash + gap
    return out


def hatch_segments(h: dict) -> list[tuple[float, float, float, float]]:
    """Отрезки штриховки по ГОСТ 2.306: металл — наклонные линии; неметалл — сетка; бетон — штрихи двух
    направлений; стекло — группы коротких параллельных штрихов."""
    b, s, a = h["boundary"], h["step"], h["angle"]
    if h["pattern"] == "metal":
        return _family(b, a, s)
    if h["pattern"] == "nonmetal":
        return _family(b, a, s) + _family(b, a + 90, s)
    if h["pattern"] == "concrete":
        return _dashes(_family(b, a, s * 1.5), s * 1.5, s) + _dashes(_family(b, a + 90, s * 3), s * 0.6, s * 1.9, s)
    if h["pattern"] == "glass":
        out = []
        for k in range(3):  # три штриха в группе
            out += _dashes(_family(b, a, s * 6, phase=k * s * 0.5), s * 1.5, s * 4.5)
        return out
    raise ValueError("неизвестный вид штриховки")
