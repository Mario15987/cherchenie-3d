"""Геометрия: контуры эскиза, привязки, починка разрывов, твёрдое тело (manifold3d), экспорт STL/OBJ."""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from .model import arc_points, arc_sweep

TOL = 1e-3          # совпадение концов при поиске контуров, мм
ARC_STEP_DEG = 6.0  # шаг разбиения дуг и окружностей на отрезки


# ---------------------------------------------------------------- контуры
def _key(p, tol=TOL):
    return (round(p[0] / tol), round(p[1] / tol))


def _segments(entities):
    """Отрезки и дуги как рёбра графа: (id, start, end, точки по пути)."""
    out = []
    for e in entities:
        if e["type"] == "line":
            a, b = (e["x1"], e["y1"]), (e["x2"], e["y2"])
            if math.dist(a, b) > TOL:
                out.append((e["id"], a, b, [a, b]))
        elif e["type"] == "arc":
            a, b = arc_points(e)
            out.append((e["id"], a, b, tessellate_arc(e)))
    return out


def tessellate_arc(e) -> list[tuple[float, float]]:
    sweep = arc_sweep(e)
    n = max(2, int(math.ceil(sweep / ARC_STEP_DEG)))
    return [(e["cx"] + e["r"] * math.cos(math.radians(e["a0"] + sweep * i / n)),
             e["cy"] + e["r"] * math.sin(math.radians(e["a0"] + sweep * i / n))) for i in range(n + 1)]


def circle_polygon(cx, cy, r) -> list[tuple[float, float]]:
    n = max(24, int(360 / ARC_STEP_DEG))
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


@dataclass
class Contours:
    polygons: list[list[tuple[float, float]]]
    open_chains: int
    dangling: list[tuple[float, float]]  # свободные концы незамкнутых цепочек

    @property
    def closed(self) -> int:
        return len(self.polygons)


def contours(entities) -> Contours:
    """Замкнутые контуры: компоненты графа, где у каждого узла ровно две кривые. Окружности — отдельные контуры."""
    segs = _segments(entities)
    adj: dict = {}
    for i, (_, a, b, _) in enumerate(segs):
        adj.setdefault(_key(a), []).append(i)
        adj.setdefault(_key(b), []).append(i)
    seen = set()
    polygons, dangling, open_chains = [], [], 0
    for start in range(len(segs)):
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            i = stack.pop()
            comp.append(i)
            for k in (_key(segs[i][1]), _key(segs[i][2])):
                for j in adj[k]:
                    if j not in seen:
                        seen.add(j)
                        stack.append(j)
        nodes = {k for i in comp for k in (_key(segs[i][1]), _key(segs[i][2]))}
        if all(len(adj[k]) == 2 for k in nodes) and (len(comp) >= 2 or _key(segs[comp[0]][1]) == _key(segs[comp[0]][2])):
            polygons.append(_walk(segs, adj, comp))
        else:
            open_chains += 1
            for k in nodes:
                if len(adj[k]) == 1:
                    i = adj[k][0]
                    dangling.append(segs[i][1] if _key(segs[i][1]) == k else segs[i][2])
    for e in entities:
        if e["type"] == "circle" and e["r"] > TOL:
            polygons.append(circle_polygon(e["cx"], e["cy"], e["r"]))
    return Contours(polygons, open_chains, dangling)


def _walk(segs, adj, comp) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    cur = comp[0]
    at = _key(segs[cur][1])
    for _ in range(len(comp)):
        _, a, b, path = segs[cur]
        forward = _key(a) == at
        pts.extend((path if forward else path[::-1])[:-1])
        at = _key(b) if forward else _key(a)
        nxt = [j for j in adj[at] if j != cur]
        if not nxt:
            break
        cur = nxt[0]
    return pts


def _walk_ordered(segs) -> list[tuple[float, float]]:
    """Точки контура по уже упорядоченным рёбрам (id, a, b, путь): каждое ребро разворачивается по ходу обхода."""
    pts: list[tuple[float, float]] = []
    at = None
    for i, (_, a, b, path) in enumerate(segs):
        if i == 0:
            nxt = segs[1] if len(segs) > 1 else segs[0]
            forward = _key(b) in (_key(nxt[1]), _key(nxt[2]))
        else:
            forward = _key(a) == at
        seq = path if forward else path[::-1]
        pts.extend(seq[:-1])
        at = _key(seq[-1])
    return pts


def perpendicular_foot(e, base):
    """Основание перпендикуляра из base на отрезок (если внутри него) или на окружность/дугу."""
    if e["type"] == "line":
        dx, dy = e["x2"] - e["x1"], e["y2"] - e["y1"]
        L2 = dx * dx + dy * dy
        if L2 < 1e-12:
            return None
        t = ((base[0] - e["x1"]) * dx + (base[1] - e["y1"]) * dy) / L2
        return (e["x1"] + t * dx, e["y1"] + t * dy) if -1e-9 <= t <= 1 + 1e-9 else None
    d = math.hypot(base[0] - e["cx"], base[1] - e["cy"])
    if d < 1e-9:
        return None
    p = (e["cx"] + (base[0] - e["cx"]) / d * e["r"], e["cy"] + (base[1] - e["cy"]) / d * e["r"])
    return p if _on_arc(e, *p) else None


def tangent_points(e, base) -> list[tuple[float, float]]:
    """Точки касания прямых из base к окружности или дуге."""
    if e["type"] not in ("circle", "arc"):
        return []
    dx, dy = base[0] - e["cx"], base[1] - e["cy"]
    d = math.hypot(dx, dy)
    if d <= e["r"] + 1e-9:
        return []
    a = math.atan2(dy, dx)
    b = math.acos(e["r"] / d)
    pts = [(e["cx"] + e["r"] * math.cos(a + s * b), e["cy"] + e["r"] * math.sin(a + s * b)) for s in (1, -1)]
    return [p for p in pts if _on_arc(e, *p)]


def fix_gaps(entities, tol: float = 0.5) -> int:
    """Сводит близкие свободные концы отрезков в одну точку. Возвращает число исправленных стыков."""
    ends = []  # (entity, 'p1'|'p2', point)
    count_at: dict = {}
    for e in entities:
        if e["type"] == "line" and e["style"] == "main":
            for tag, p in (("p1", (e["x1"], e["y1"])), ("p2", (e["x2"], e["y2"]))):
                ends.append((e, tag, p))
                count_at[_key(p)] = count_at.get(_key(p), 0) + 1
        elif e["type"] == "arc" and e["style"] == "main":
            for p in arc_points(e):
                count_at[_key(p)] = count_at.get(_key(p), 0) + 1
    arc_ends = [p for e in entities if e["type"] == "arc" and e["style"] == "main" for p in arc_points(e)]
    free = [x for x in ends if count_at[_key(x[2])] == 1]
    fixed, used = 0, set()
    for i, (e, tag, p) in enumerate(free):
        if i in used:
            continue
        # Сначала тянем к концу дуги (дугу не двигаем), иначе — к ближайшему другому свободному концу.
        target, j_best, best = None, None, tol
        for q in arc_ends:
            if count_at.get(_key(q), 0) == 1 and 0 < math.dist(p, q) <= best:
                target, best = q, math.dist(p, q)
        for j, (e2, _, q) in enumerate(free):
            if j != i and j not in used and e2 is not e and 0 < math.dist(p, q) <= best:
                target, j_best, best = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), j, math.dist(p, q)
        if target is None:
            continue
        _set_end(e, tag, target)
        if j_best is not None:
            e2, tag2, _ = free[j_best]
            _set_end(e2, tag2, target)
            used.add(j_best)
        used.add(i)
        fixed += 1
    return fixed


def _set_end(e, tag, p):
    if tag == "p1":
        e["x1"], e["y1"] = p
    else:
        e["x2"], e["y2"] = p


# ---------------------------------------------------------------- привязки
def snap_points(entities) -> list[tuple[float, float, str]]:
    """Характерные точки: концы, середины, центры, квадранты и пересечения."""
    pts = [(0.0, 0.0, "начало координат")]
    curves = [e for e in entities if e["type"] in ("line", "circle", "arc")]
    for e in curves:
        if e["type"] == "line":
            pts += [(e["x1"], e["y1"], "конец"), (e["x2"], e["y2"], "конец"),
                    ((e["x1"] + e["x2"]) / 2, (e["y1"] + e["y2"]) / 2, "середина")]
        else:
            pts.append((e["cx"], e["cy"], "центр"))
            if e["type"] == "arc":
                pts += [(*p, "конец") for p in arc_points(e)]
            else:
                pts += [(e["cx"] + dx * e["r"], e["cy"] + dy * e["r"], "квадрант") for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1))]
    for i in range(len(curves)):
        for j in range(i + 1, len(curves)):
            pts += [(x, y, "пересечение") for x, y in intersect(curves[i], curves[j])]
    return pts


def _on_arc(e, x, y) -> bool:
    if e["type"] != "arc":
        return True
    ang = math.degrees(math.atan2(y - e["cy"], x - e["cx"])) % 360.0
    return (ang - e["a0"]) % 360.0 <= arc_sweep(e) + 1e-6


def _on_seg(e, x, y) -> bool:
    return (min(e["x1"], e["x2"]) - 1e-6 <= x <= max(e["x1"], e["x2"]) + 1e-6
            and min(e["y1"], e["y2"]) - 1e-6 <= y <= max(e["y1"], e["y2"]) + 1e-6)


def intersect(a, b) -> list[tuple[float, float]]:
    if a["type"] != "line" and b["type"] == "line":
        a, b = b, a
    if a["type"] == "line" and b["type"] == "line":
        x1, y1, x2, y2 = a["x1"], a["y1"], a["x2"], a["y2"]
        x3, y3, x4, y4 = b["x1"], b["y1"], b["x2"], b["y2"]
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-12:
            return []
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / d
        return [(x1 + t * (x2 - x1), y1 + t * (y2 - y1))] if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9 else []
    if a["type"] == "line":
        dx, dy = a["x2"] - a["x1"], a["y2"] - a["y1"]
        fx, fy = a["x1"] - b["cx"], a["y1"] - b["cy"]
        A, B, C = dx * dx + dy * dy, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - b["r"] ** 2
        disc = B * B - 4 * A * C
        if A < 1e-12 or disc < 0:
            return []
        out = []
        for s in {(-B - math.sqrt(disc)) / (2 * A), (-B + math.sqrt(disc)) / (2 * A)}:
            x, y = a["x1"] + s * dx, a["y1"] + s * dy
            if -1e-9 <= s <= 1 + 1e-9 and _on_arc(b, x, y):
                out.append((x, y))
        return out
    # окружность/дуга с окружностью/дугой
    d = math.hypot(b["cx"] - a["cx"], b["cy"] - a["cy"])
    if d < 1e-9 or d > a["r"] + b["r"] or d < abs(a["r"] - b["r"]):
        return []
    l = (a["r"] ** 2 - b["r"] ** 2 + d * d) / (2 * d)
    h = math.sqrt(max(a["r"] ** 2 - l * l, 0.0))
    mx, my = a["cx"] + l * (b["cx"] - a["cx"]) / d, a["cy"] + l * (b["cy"] - a["cy"]) / d
    out = []
    for sgn in (1, -1):
        x, y = mx + sgn * h * (b["cy"] - a["cy"]) / d, my - sgn * h * (b["cx"] - a["cx"]) / d
        if _on_arc(a, x, y) and _on_arc(b, x, y):
            out.append((x, y))
    return out


def distance_to(e, x, y) -> float:
    """Расстояние от точки до примитива — для выбора щелчком."""
    if e["type"] in ("line", "dim"):
        ax, ay, bx, by = e["x1"], e["y1"], e["x2"], e["y2"]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
        return math.hypot(x - ax - t * dx, y - ay - t * dy)
    d = abs(math.hypot(x - e["cx"], y - e["cy"]) - e["r"])
    return d if _on_arc(e, x, y) else math.inf


# ---------------------------------------------------------------- твёрдое тело
@dataclass
class Solid:
    verts: np.ndarray  # (N, 3) float32
    faces: np.ndarray  # (M, 3) int32
    statuses: dict     # id операции -> текст ошибки или None
    manifold: object = None  # тело manifold3d — для проекций видов и лучей
    handles: list = field(default_factory=list)  # ручки граней для правки мышью в 3D (см. extrude_handle)

    @property
    def empty(self) -> bool:
        return len(self.faces) == 0

    def bbox(self):
        if self.empty:
            return np.zeros(3), np.zeros(3)
        return self.verts.min(axis=0), self.verts.max(axis=0)

    @property
    def volume(self) -> float:
        return float(self.manifold.volume()) if self.manifold is not None else 0.0


def feature_polygons(f) -> list:
    """Профиль операции из её эскиза (старые файлы без эскиза — из сохранённого профиля)."""
    sketch = f.get("sketch") or []
    if sketch:
        from .model import Project

        c = contours(Project.profile_of(sketch))
        if c.open_chains and not c.closed:
            raise ValueError(f"контур эскиза не замкнут (незамкнутых цепочек: {c.open_chains})")
        return c.polygons
    return [p for p in f.get("polygons", []) if len(p) >= 3]


def revolve_axis(f):
    """Ось вращения: первая осевая линия эскиза операции (или ось из параметров)."""
    if f.get("axis"):
        return f["axis"]
    for e in f.get("sketch", []):
        if e["type"] == "line" and e["style"] == "axis":
            return [e["x1"], e["y1"], e["x2"], e["y2"]]
    raise ValueError("в эскизе нет осевой линии — ось вращения")


def _cross_section(polys):
    import manifold3d as m3d

    polys = [np.asarray(p, dtype=float) for p in polys if len(p) >= 3]
    if not polys:
        raise ValueError("в профиле нет замкнутых контуров")
    # Чётно-нечётное правило: вложенный контур — отверстие, контур в отверстии — снова материал.
    cs = m3d.CrossSection(polys, m3d.FillRule.EvenOdd)
    if cs.area() <= 1e-9:
        raise ValueError("площадь профиля равна нулю")
    return cs


def _revolve(polys, axis, angle):
    """Тело вращения профиля плоскости XY вокруг оси (x1, y1)–(x2, y2) на угол angle°."""
    import manifold3d as m3d

    if not 0 < angle <= 360:
        raise ValueError("угол вращения от 0 до 360°")
    ax, ay, bx, by = axis
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-9:
        raise ValueError("осевая линия нулевой длины")
    a = np.array([(bx - ax) / L, (by - ay) / L, 0.0])   # направление оси
    n = np.array([-a[1], a[0], 0.0])                    # перпендикуляр в плоскости эскиза
    local = []
    for p in polys:
        q = np.asarray(p, float) - [ax, ay]
        local.append(np.stack([q @ n[:2], q @ a[:2]], axis=1))  # (расстояние до оси, положение вдоль оси)
    us = np.concatenate([l[:, 0] for l in local])
    if us.max() > 1e-6 and us.min() < -1e-6:
        raise ValueError("профиль пересекает ось вращения")
    if us.max() <= 1e-6:  # профиль по другую сторону оси — смотрим с другой стороны
        n = -n
        local = [np.stack([-l[:, 0], l[:, 1]], axis=1) for l in local]
    cs = m3d.CrossSection([np.ascontiguousarray(l) for l in local], m3d.FillRule.EvenOdd)
    body = cs.revolve(max(24, int(angle / 4)), float(angle))
    # После revolve: X — радиус, ось вращения — Z. Возвращаем в мир: X→n, Y→Z мира, Z→ось.
    M = np.column_stack([n, [0.0, 0.0, 1.0], a, [ax, ay, 0.0]])
    return body.transform(M.tolist())


def _apply(body, tool, op):
    if op == "add" or body is None:
        if op in ("cut", "intersect") and body is None:
            raise ValueError("нечего вырезать: тела ещё нет")
        return tool if body is None else body + tool
    before = body.volume()
    out = body - tool if op == "cut" else body ^ tool
    if op == "cut" and abs(out.volume() - before) < 1e-9:
        raise ValueError("вырез не пересекает тело")
    if out.is_empty():
        raise ValueError("после операции тело пустое")
    return out


def _sphere(r, segments=20):
    """Сегментов кратно 4: полюса и экватор дают точное смещение граней, параллельных осям."""
    import manifold3d as m3d

    return m3d.Manifold.sphere(r, segments)


def _lean(body):
    """Сливает компланарные треугольники. Без этого сумма Минковского на теле после скругления
    (тысячи мелких граней) считается минутами."""
    return body.simplify(1e-4)


def _octahedron(c):
    import manifold3d as m3d

    return m3d.Manifold.hull_points(np.array([[c, 0, 0], [-c, 0, 0], [0, c, 0], [0, -c, 0], [0, 0, c], [0, 0, -c]], float))


_CACHE: dict[str, tuple] = {}   # префикс дерева -> (тело, статус): правка в конце дерева не пересчитывает начало


def extrude_handle(f, top: float, had_body: bool) -> dict | None:
    """Ручка прямого редактирования: горизонтальная грань, которую задаёт число операции. Выдавливание — верхняя грань
    на высоте base + H (тянется вверх — H растёт); вырез на глубину — дно на top − depth (тянется вниз — глубина растёт).
    Считается так же, как в build_solid. Вырез «через всё», вращение, оболочка, скругление ручек не имеют."""
    kind, op = f["type"], f.get("op", "add")
    if kind == "cut" or (kind == "extrude" and op == "cut"):
        if f.get("through") or not had_body:
            return None
        d = float(f.get("depth", f.get("height", 5)))
        return {"fid": f["id"], "param": "depth", "z": top - d, "dir": -1, "base": top, "value": d}
    if kind == "extrude":
        h = float(f["height"])
        z0 = top if f.get("base") == "top" and had_body else 0.0
        return {"fid": f["id"], "param": "height", "z": z0 + h, "dir": 1, "base": z0, "value": h}
    return None


def points_in_polygons(xs, ys, polys) -> np.ndarray:
    """Точки внутри профиля по правилу чёт-нечет: контур с отверстиями даётся всеми его многоугольниками."""
    xs, ys = np.atleast_1d(np.asarray(xs, float)), np.atleast_1d(np.asarray(ys, float))
    inside = np.zeros(xs.shape, bool)
    for poly in polys:
        p = np.asarray(poly, float)
        x1, y1 = p[:, 0], p[:, 1]
        x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        for a, b, c, d in zip(x1, y1, x2, y2):
            cross = (b > ys) != (d > ys)
            with np.errstate(divide="ignore", invalid="ignore"):
                xi = a + (ys - b) * (c - a) / (d - b)
            inside ^= cross & (xs < xi)
    return inside


def _feature(features, fid):
    return next((f for f in features if f["id"] == fid), None)


def handle_at(solid: Solid, features, point, normal) -> dict | None:
    """Ручка под точкой грани: грань горизонтальна (нормаль +Z), лежит на высоте ручки и внутри профиля операции.
    Из нескольких подходящих — последняя по дереву: её грань видна поверх прежних."""
    if solid.empty or normal[2] < 0.98:
        return None
    lo, hi = solid.bbox()
    tol = max(1e-3, 1e-5 * float(np.linalg.norm(hi - lo)))
    for h in reversed(solid.handles):
        f = _feature(features, h["fid"])
        if f is None or abs(float(point[2]) - h["z"]) > tol:
            continue
        try:
            polys = feature_polygons(f)
        except ValueError:
            continue
        if points_in_polygons(point[0], point[1], polys)[0]:
            return {**h, "name": f["name"]}
    return None


def face_triangles(solid: Solid, features, handle) -> np.ndarray:
    """Номера треугольников грани ручки: горизонтальные, на её высоте, центр — внутри профиля операции."""
    if solid.empty:
        return np.zeros(0, np.int64)
    v = solid.verts[solid.faces].astype(np.float64)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    c = v.mean(axis=1)
    lo, hi = solid.bbox()
    tol = max(1e-3, 1e-5 * float(np.linalg.norm(hi - lo)))
    mask = (n[:, 2] > 0.999) & (np.abs(c[:, 2] - handle["z"]) <= tol)
    f = _feature(features, handle["fid"])
    if f is not None and mask.any():
        try:
            idx = np.flatnonzero(mask)
            mask[idx] = points_in_polygons(c[idx, 0], c[idx, 1], feature_polygons(f))
        except ValueError:
            pass
    return np.flatnonzero(mask)


def ray_hit(solid: Solid, origin, direction):
    """Ближайшее пересечение луча с телом (Мёллер — Трумбор по всем треугольникам): точка, нормаль, номер треугольника."""
    if solid.empty:
        return None
    o, d = np.asarray(origin, float), np.asarray(direction, float)
    v = solid.verts[solid.faces].astype(np.float64)
    e1, e2 = v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = o - v[:, 0]
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    w = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= -1e-9) & (w >= -1e-9) & (u + w <= 1 + 1e-9) & (t > 1e-9)
    if not hit.any():
        return None
    i = int(np.flatnonzero(hit)[np.argmin(t[hit])])
    n = np.cross(e1[i], e2[i])
    n /= np.linalg.norm(n) + 1e-12
    return {"point": o + t[i] * d, "normal": n, "tri": i, "t": float(t[i])}


def with_handle_value(features, handle, value) -> list:
    """Копия дерева с новым числом ручки (исходные операции не меняются) — для фантома при перетаскивании."""
    out = []
    for f in features:
        if f["id"] == handle["fid"]:
            f = {**f, handle["param"]: float(value)}
            if handle["param"] == "depth":
                f["through"] = False
        out.append(f)
    return out


def handle_tool(features, handle, value) -> Solid:
    """Быстрый фантом — только тело самой операции с новым числом (для деревьев со скруглениями и оболочками)."""
    f = _feature(features, handle["fid"])
    cs = _cross_section(feature_polygons(f))
    a, b = handle["base"], handle["base"] + handle["dir"] * float(value)
    lo, hi = min(a, b), max(a, b)
    body = cs.extrude(max(hi - lo, 1e-6)).translate([0.0, 0.0, lo])
    mesh = body.to_mesh()
    return Solid(np.asarray(mesh.vert_properties, np.float32)[:, :3], np.asarray(mesh.tri_verts, np.int32), {}, body)


SLOW_FEATURES = ("fillet3d", "chamfer3d", "shell")


def build_solid(features) -> Solid:
    """Выполняет дерево построения по порядку. Профиль каждой операции берётся из её эскиза — правка размеров
    в эскизе перестраивает модель. Ошибка одной операции не останавливает остальные."""
    import hashlib
    import json

    body = None
    statuses = {}
    handles = []
    key = ""
    for f in features:
        if f.get("suppressed"):
            continue
        had_body = body is not None and not body.is_empty()
        top = body.bounding_box()[5] if had_body else 0.0
        key = hashlib.sha1((key + json.dumps(f, sort_keys=True, default=str)).encode()).hexdigest()
        if key in _CACHE:
            body, statuses[f["id"]] = _CACHE[key]
            h = extrude_handle(f, top, had_body) if statuses[f["id"]] is None else None
            if h:
                handles.append(h)
            continue
        try:
            kind, op = f["type"], f.get("op", "add")
            box = body.bounding_box() if body is not None and not body.is_empty() else (0, 0, 0, 0, 0, 0)
            zmin, zmax = box[2], box[5]
            if kind in ("extrude", "cut"):
                if kind == "cut":
                    op = "cut"
                cs = _cross_section(feature_polygons(f))
                if op == "cut":
                    if body is None:
                        raise ValueError("нечего вырезать: тела ещё нет")
                    if f.get("through"):
                        z0, h = zmin - 1.0, (zmax - zmin) + 2.0
                    else:
                        d = float(f.get("depth", f.get("height", 5)))
                        if d <= 0:
                            raise ValueError("глубина должна быть больше нуля")
                        z0, h = zmax - d, d + 1.0
                else:
                    h = float(f["height"])
                    if h <= 0:
                        raise ValueError("высота должна быть больше нуля")
                    z0 = zmax if f.get("base") == "top" and body is not None else 0.0
                body = _apply(body, cs.extrude(h).translate([0.0, 0.0, z0]), op)
            elif kind == "revolve":
                tool = _revolve(feature_polygons(f), revolve_axis(f), float(f.get("angle", 360)))
                body = _apply(body, tool, op)
            elif kind == "shell":
                if body is None:
                    raise ValueError("нет тела для оболочки")
                t = float(f["thickness"])
                if t <= 0:
                    raise ValueError("толщина стенки должна быть больше нуля")
                inner = _lean(body).minkowski_difference(_sphere(t, 12))
                if inner.is_empty():
                    raise ValueError("стенка толще половины детали")
                if f.get("open_top", True):
                    # Открытый верх: внутренность продолжается вверх за пределы тела.
                    inner = inner + inner.translate([0.0, 0.0, 2 * t + 1.0])
                body = _lean(body - inner)
            elif kind in ("fillet3d", "chamfer3d"):
                if body is None:
                    raise ValueError("нет тела для обработки рёбер")
                r = float(f["size"])
                if r <= 0:
                    raise ValueError("размер должен быть больше нуля")
                tool = _sphere(r, 16) if kind == "fillet3d" else _octahedron(r)
                # Морфологическое «открытие»: эрозия и обратное наращивание скругляют (или срезают) все выпуклые рёбра.
                core = _lean(_lean(body).minkowski_difference(tool))
                if core.is_empty():
                    raise ValueError("радиус больше половины толщины детали")
                body = _lean(core.minkowski_sum(tool))
            else:
                raise ValueError(f"неизвестная операция {kind}")
            statuses[f["id"]] = None
        except Exception as exc:  # noqa: BLE001 — любая ошибка операции показывается в дереве
            statuses[f["id"]] = str(exc)
        if len(_CACHE) > 200:
            _CACHE.clear()
        _CACHE[key] = (body, statuses[f["id"]])
        h = extrude_handle(f, top, had_body) if statuses[f["id"]] is None else None
        if h:
            handles.append(h)
    if body is None or body.is_empty():
        return Solid(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32), statuses)
    mesh = body.to_mesh()
    return Solid(np.asarray(mesh.vert_properties, np.float32)[:, :3], np.asarray(mesh.tri_verts, np.int32), statuses, body, handles)


def feature_edges(verts: np.ndarray, faces: np.ndarray, angle_deg: float = 25.0) -> np.ndarray:
    """Рёбра, где соседние треугольники расходятся больше чем на angle_deg, — контур детали для отрисовки."""
    if len(faces) == 0:
        return np.zeros((0, 3), np.float32)
    v = verts[faces]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    owner = np.tile(np.arange(len(faces)), 3)
    key = np.sort(edges, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, owner = key[order], owner[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    i = np.nonzero(same)[0]
    cos = np.einsum("ij,ij->i", n[owner[i]], n[owner[i + 1]])
    sharp = key[i][cos < math.cos(math.radians(angle_deg))]
    # Рёбра без пары (не должно быть у замкнутого тела) тоже рисуем.
    paired = np.zeros(len(key), bool)
    paired[i] = paired[i + 1] = True
    sharp = np.concatenate([sharp, key[~paired]])
    return verts[sharp.reshape(-1)].astype(np.float32)


def export_stl(path: str, solid: Solid, name: str = "part") -> None:
    v = solid.verts[solid.faces]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    with open(path, "wb") as f:
        f.write(name.encode("ascii", "replace")[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(solid.faces)))
        rec = np.zeros(len(solid.faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        rec["n"], rec["v"] = n, v
        f.write(rec.tobytes())


def export_obj(path: str, solid: Solid, name: str = "part") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Черчение 3D\no {name}\n")
        f.writelines(f"v {x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in solid.verts)
        f.writelines(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in solid.faces)
