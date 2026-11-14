"""Чертёж по 3D-модели: три стандартных вида (ГОСТ 2.305, метод первого угла) с невидимыми линиями.

Рёбра вида — острые рёбра сетки и силуэты (ребро между гранью к наблюдателю и гранью от него). Видимость —
лучом от точки ребра к наблюдателю: если луч упирается в тело, участок невидим (штриховая линия).
"""
from __future__ import annotations

import math

import numpy as np

from .model import default_frame, make_dim, make_line, sheet_size
from .stamp import frame_rect, stamp_size

# Направление к наблюдателю и оси листа (вправо, вверх) для каждого вида.
VIEWS = {
    "front": (np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    "top": (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])),
    "left": (np.array([-1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
}
# Ряд ГОСТ 2.302 от крупного к мелкому: «Чертёж по модели» берёт первый, при котором виды помещаются.
SCALES = [(10, "10:1"), (5, "5:1"), (4, "4:1"), (2.5, "2,5:1"), (2, "2:1"), (1, "1:1"), (0.5, "1:2"), (0.4, "1:2,5"),
          (0.25, "1:4"), (0.2, "1:5"), (0.1, "1:10"), (0.05, "1:20"), (0.02, "1:50"), (0.01, "1:100")]

# Аксонометрия по ГОСТ 2.317: направление к наблюдателю и оси листа. Камера смотрит на переднюю (−Y), правую (+X)
# и верхнюю грани. Изометрия: все оси под 120°, коэффициент 0,82; диметрия: x и z — 0,94, y — 0,47.
_S2, _S3, _S6 = math.sqrt(2), math.sqrt(3), math.sqrt(6)
ISO_K = _S6 / 2            # 1,2247: приведённая изометрия — коэффициент по осям принят 1 (изображение крупнее в 1,22)
DIM_K = 1 / 0.9428         # приведённая диметрия: по x и z — 1, по y — 0,5


def axo_basis(azimuth_deg: float, elevation_deg: float):
    """(к наблюдателю, вправо, вверх) для камеры с азимутом от оси X и возвышением над плоскостью XY."""
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    to_viewer = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    ux = np.array([-math.sin(az), math.cos(az), 0.0])
    return to_viewer, ux, np.cross(to_viewer, ux)


ISO_ANGLES = (-45.0, math.degrees(math.asin(1 / _S3)))                       # возвышение 35,264°
DIM_ANGLES = (-90.0 + math.degrees(math.asin(math.sqrt(1 / 8))), math.degrees(math.asin(1 / 3)))   # −69,295°; 19,471°
AXO = {"iso": (axo_basis(*ISO_ANGLES), ISO_K), "dim": (axo_basis(*DIM_ANGLES), DIM_K)}


def _edges(verts, faces, view_dir, angle_deg=25.0):
    """Острые рёбра и силуэты для данного направления взгляда: пары индексов вершин и наружная нормаль ребра.

    Грань относится к одному из трёх классов: к зрителю, от зрителя, вдоль взгляда (стенка, видимая ребром).
    Силуэт — ребро между гранями разных классов: так контур скруглённого тела не пропадает, хотя его
    грани-фасетки сходятся под малым углом и острыми не считаются."""
    v = verts[faces].astype(float)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    owner = np.tile(np.arange(len(faces)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, owner = key[order], owner[order]
    same = np.nonzero(np.all(key[1:] == key[:-1], axis=1))[0]
    n1, n2 = n[owner[same]], n[owner[same + 1]]
    sharp = np.einsum("ij,ij->i", n1, n2) < math.cos(math.radians(angle_deg))
    eps = 1e-3
    c1, c2 = np.sign(np.where(np.abs(n1 @ view_dir) < eps, 0, n1 @ view_dir)), np.sign(np.where(np.abs(n2 @ view_dir) < eps, 0, n2 @ view_dir))
    pick = sharp | (c1 != c2)
    out_n = n1[pick] + n2[pick]
    out_n /= np.linalg.norm(out_n, axis=1, keepdims=True) + 1e-12
    return key[same][pick], out_n


def edge_chains(pairs) -> list[list[int]]:
    """Рёбра (пары вершин) → цепочки вершин: ребро за ребром, пока в вершине сходятся ровно два ребра. Нужны, чтобы
    штрих невидимой линии шёл по всей дуге окружности, а не начинался заново на каждом коротком ребре сетки."""
    adj: dict[int, list[int]] = {}
    for k, (i, j) in enumerate(pairs):
        adj.setdefault(int(i), []).append(k)
        adj.setdefault(int(j), []).append(k)
    used = [False] * len(pairs)
    chains = []

    def walk(start, k):
        chain, v = [start], start
        while k is not None and not used[k]:
            used[k] = True
            i, j = int(pairs[k][0]), int(pairs[k][1])
            v = j if v == i else i
            chain.append(v)
            nxt = [e for e in adj[v] if not used[e]]
            k = nxt[0] if len(adj[v]) == 2 and nxt else None
        return chain

    for v, es in adj.items():            # сначала от концов и развилок, потом — замкнутые кольца
        if len(es) != 2:
            for k in es:
                if not used[k]:
                    chains.append(walk(v, k))
    for k, (i, _) in enumerate(pairs):
        if not used[k]:
            chains.append(walk(int(i), k))
    return chains


def dash_chains(verts, chains, dash: float, gap: float) -> np.ndarray:
    """Штрихи вдоль цепочек: массив (2N, 3) концов отрезков для рисования линиями."""
    out = []
    period = dash + gap
    for chain in chains:
        pts = np.asarray(verts, float)[chain]
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(s[-1])
        if total < 1e-9:
            continue
        n = max(1, int(math.ceil(total / period)))
        starts = np.arange(n) * period
        ends = np.minimum(starts + dash, total)
        marks = np.unique(np.concatenate([starts, ends, s]))
        on = (marks[:-1] % period) < dash - 1e-9
        a, b = marks[:-1][on], marks[1:][on]
        if not len(a):
            continue
        at = lambda t: np.stack([np.interp(t, s, pts[:, c]) for c in range(3)], axis=1)  # noqa: E731
        pair = np.empty((2 * len(a), 3))
        pair[0::2], pair[1::2] = at(a), at(b)
        out.append(pair)
    return np.concatenate(out) if out else np.zeros((0, 3))


def view_edges(solid, to_viewer) -> np.ndarray:
    """Пары вершин острых рёбер и очерка тела для направления взгляда (для технического вида в 3D)."""
    pairs, _ = _edges(solid.verts.astype(float), solid.faces, np.asarray(to_viewer, float))
    return pairs


def model_dims(solid, features) -> list[dict]:
    """Размеры для показа прямо на 3D-модели: габариты L (по X), W (по Y), H (по Z) вдоль рёбер габаритного
    параллелепипеда и Ø окружностей из эскизов выдавливаний и вырезов. Каждый: kind, text, a, b (размерная линия),
    ext (выносные линии), at (точка надписи)."""
    if solid.empty:
        return []
    lo, hi = (np.asarray(v, float) for v in solid.bbox())
    off = float(np.clip(0.12 * np.linalg.norm(hi - lo), 6.0, 40.0))
    fmt = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")  # noqa: E731
    P = lambda x, y, z: np.array([x, y, z], float)  # noqa: E731
    out = []

    def add(kind, value, a, b, ext, prefix):
        out.append({"kind": kind, "value": float(value), "text": f"{prefix}{fmt(value)}", "a": a, "b": b, "ext": ext, "at": (a + b) / 2})

    yL, xW, xH = lo[1] - off, hi[0] + off, lo[0] - off
    add("L", hi[0] - lo[0], P(lo[0], yL, lo[2]), P(hi[0], yL, lo[2]),
        [(P(lo[0], lo[1], lo[2]), P(lo[0], yL - off * 0.2, lo[2])), (P(hi[0], lo[1], lo[2]), P(hi[0], yL - off * 0.2, lo[2]))], "L: ")
    add("W", hi[1] - lo[1], P(xW, lo[1], lo[2]), P(xW, hi[1], lo[2]),
        [(P(hi[0], lo[1], lo[2]), P(xW + off * 0.2, lo[1], lo[2])), (P(hi[0], hi[1], lo[2]), P(xW + off * 0.2, hi[1], lo[2]))], "W: ")
    add("H", hi[2] - lo[2], P(xH, lo[1], lo[2]), P(xH, lo[1], hi[2]),
        [(P(lo[0], lo[1], lo[2]), P(xH - off * 0.2, lo[1], lo[2])), (P(lo[0], lo[1], hi[2]), P(xH - off * 0.2, lo[1], hi[2]))], "H: ")
    handles = {h["fid"]: h for h in solid.handles}
    seen = set()
    d = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)          # вдоль экрана в изометрии ГОСТ
    for f in features:
        if f.get("suppressed") or f["type"] not in ("extrude", "cut") or solid.statuses.get(f["id"]):
            continue
        h = handles.get(f["id"])
        z = hi[2] if h is None else (h["z"] if h["dir"] > 0 else h["base"])
        for e in f.get("sketch", []):
            if e["type"] != "circle" or e.get("style") != "main":
                continue
            key = (round(e["cx"], 3), round(e["cy"], 3), round(e["r"], 3))
            if key in seen:
                continue
            seen.add(key)
            c = P(e["cx"], e["cy"], z)
            a, b = c - d * e["r"], c + d * e["r"]
            tail = b + d * off * 0.8
            out.append({"kind": "D", "value": 2 * e["r"], "text": f"Ø{fmt(2 * e['r'])}", "a": a, "b": b, "ext": [(b, tail)], "at": tail})
    return out


def _visible(manifold, p, to_viewer, reach):
    hits = manifold.ray_cast((p + to_viewer * 0.02).tolist(), (p + to_viewer * reach).tolist())
    return not any(h.distance * reach > 0.03 for h in hits)


_NUDGE = 0.01   # мм: точку ребра чуть выносим наружу, чтобы луч не скользил по своей же грани


def project_view(solid, view, samples_per_mm: float = 0.6):
    """Видимые и невидимые отрезки вида в координатах листа (масштаб 1:1, без сдвига). view — имя стандартного вида
    или тройка (к наблюдателю, вправо, вверх) для аксонометрии."""
    to_viewer, ux, uy = VIEWS[view] if isinstance(view, str) else view
    verts, faces = solid.verts.astype(float), solid.faces
    lo, hi = solid.bbox()
    reach = float(np.linalg.norm(hi - lo)) * 2 + 10
    vis, hid = [], []
    pairs, normals = _edges(verts, faces, to_viewer)
    for (i, j), nrm in zip(pairs, normals):
        a, b = verts[i], verts[j]
        L = float(np.linalg.norm(b - a))
        if L < 1e-6:
            continue
        k = int(min(24, max(1, math.ceil(L * samples_per_mm))))
        state, start = None, 0.0
        for s in range(k):
            t0, t1 = s / k, (s + 1) / k
            mid = a + (b - a) * (t0 + t1) / 2
            v = _visible(solid.manifold, mid + nrm * _NUDGE, to_viewer, reach)
            if state is None:
                state, start = v, t0
            elif v != state:
                (vis if state else hid).append((start, t0, a, b))
                state, start = v, t0
        (vis if state else hid).append((start, 1.0, a, b))

    def to2d(item):
        t0, t1, a, b = item
        p, q = a + (b - a) * t0, a + (b - a) * t1
        return (float(p @ ux), float(p @ uy), float(q @ ux), float(q @ uy))

    vis2 = _merge([to2d(x) for x in vis])
    hid2 = _merge([to2d(x) for x in hid])
    hid2 = [h for h in hid2 if not _covered(h, vis2)]  # невидимое под видимым не рисуем
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
    xs, ys = corners @ ux, corners @ uy       # у аксонометрии габарит на листе дают все восемь углов, а не два
    box = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
    return vis2, hid2, box


def axo_view(solid, kind: str = "iso", reduced: bool = True, hidden: bool = False):
    """Аксонометрия тела по ГОСТ 2.317: отрезки на листе (невидимые линии убраны; hidden=True — вернуть и их),
    окружности выходят эллипсами (ломаными по сетке тела). reduced — приведённые коэффициенты: размеры вдоль осей
    изометрии и вдоль x, z диметрии равны натуральным. Возвращает (видимые, невидимые, габарит)."""
    if kind not in AXO:
        raise ValueError("аксонометрия: iso (изометрия) или dim (диметрия)")
    basis, k = AXO[kind]
    k = k if reduced else 1.0
    vis, hid, box = project_view(solid, basis, samples_per_mm=1.0)
    sc = lambda segs: [tuple(v * k for v in s) for s in segs]  # noqa: E731
    return sc(vis), sc(hid) if hidden else [], tuple(v * k for v in box)


def _merge(segs, tol=1e-3):
    """Сливает коллинеарные отрезки, которые перекрываются или стыкуются, в один: ребро тела дробится
    треугольниками на много кусков, а штриховая линия из кусков со сбитой фазой штриха выглядит сплошной."""
    groups: dict[tuple, list] = {}
    for x1, y1, x2, y2 in segs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-4:
            continue
        dx, dy = (x2 - x1) / L, (y2 - y1) / L
        if dx < -1e-9 or (abs(dx) <= 1e-9 and dy < 0):
            dx, dy = -dx, -dy
        ang = round(math.atan2(dy, dx), 4)
        dx, dy = math.cos(ang), math.sin(ang)
        off = round(-dy * x1 + dx * y1, 3)
        t1, t2 = sorted((dx * x1 + dy * y1, dx * x2 + dy * y2))
        groups.setdefault((ang, off), []).append((t1, t2))
    out = []
    for (ang, off), spans in groups.items():
        dx, dy = math.cos(ang), math.sin(ang)
        spans.sort()
        a, b = spans[0]
        for t1, t2 in spans[1:] + [(math.inf, math.inf)]:
            if t1 <= b + tol:
                b = max(b, t2)
                continue
            out.append((dx * a - dy * off, dy * a + dx * off, dx * b - dy * off, dy * b + dx * off))
            a, b = t1, t2
    return out


def _covered(seg, visible, tol=0.05):
    """Невидимый отрезок лежит на видимом (совпадает в проекции)."""
    x1, y1, x2, y2 = seg
    for px, py in ((x1, y1), ((x1 + x2) / 2, (y1 + y2) / 2), (x2, y2)):
        if not any(_dist_seg(px, py, v) < tol for v in visible):
            return False
    return True


def _dist_seg(px, py, s):
    x1, y1, x2, y2 = s
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def make_drawing(project, solid, gap: float = 30.0, iso: bool | None = None) -> dict:
    """Заменяет сгенерированные виды на листе: главный вид, вид сверху под ним, вид слева справа от него,
    габаритные размеры. Масштаб — ближайший стандартный, при котором виды помещаются над основной надписью
    (или заданный пользователем: frame["scale_fixed"]). iso=True — ещё и изометрия ГОСТ 2.317 в правом верхнем
    углу, правее вида слева; None — как было на листе."""
    if solid.empty or solid.manifold is None:
        raise ValueError("нет тела: сначала постройте модель")
    if not project.frame:
        project.frame = default_frame()
    views = {v: project_view(solid, v) for v in VIEWS}
    if iso is None:
        iso = bool(project.frame.get("views_iso"))
    project.frame["views_iso"] = bool(iso)
    axo = axo_view(solid, "iso") if iso else None
    fx, fy, fw, fh = frame_rect(project.frame)
    STAMP_H = stamp_size(project.frame)[1]
    area = (fx + 15, fy + STAMP_H + 15, fw - 30, fh - STAMP_H - 30)
    (_, _, bf), (_, _, bt), (_, _, bl) = views["front"], views["top"], views["left"]
    W = lambda b: b[2] - b[0]  # noqa: E731
    Hh = lambda b: b[3] - b[1]  # noqa: E731
    need_w = W(bf) + W(bl) + (W(axo[2]) if axo else 0.0)
    need_h = max(Hh(bf) + Hh(bt), Hh(axo[2]) - gap if axo else 0.0)
    gaps_w = gap * (2 if axo else 1)
    fits = lambda k: need_w * k + gaps_w <= area[2] and need_h * k + gap <= area[3]  # noqa: E731
    scale, label = next(((k, lab) for k, lab in SCALES if fits(k)), SCALES[-1])
    if project.frame.get("scale_fixed"):
        fixed = next(((k, lab) for k, lab in SCALES if lab == project.frame.get("scale")), None)
        if fixed:
            scale, label = fixed
    project.frame["scale"] = label
    # Расположение: главный вид слева сверху, вид слева — справа (та же высота), вид сверху — под главным.
    total_w, total_h = need_w * scale + gaps_w, need_h * scale + gap
    left0 = area[0] + (area[2] - total_w) / 2
    top0 = area[1] + area[3] - (area[3] - total_h) / 2
    place = {
        "front": (left0, top0 - Hh(bf) * scale),
        "left": (left0 + W(bf) * scale + gap, top0 - Hh(bl) * scale),
        "top": (left0, top0 - Hh(bf) * scale - gap - Hh(bt) * scale),
    }
    project.drawing[:] = [e for e in project.drawing if e.get("gen") != "views"]
    made = 0
    if axo:
        ox = left0 + (W(bf) + W(bl)) * scale + 2 * gap
        made += len(_place_segments(project, axo[0], axo[2], ox, top0 - Hh(axo[2]) * scale, scale, "views"))
    for v, (vis, hid, b) in views.items():
        ox, oy = place[v]
        tr = lambda x, y, b=b, ox=ox, oy=oy: (ox + (x - b[0]) * scale, oy + (y - b[1]) * scale)  # noqa: E731
        for style, segs in (("main", vis), ("hidden", hid)):
            for x1, y1, x2, y2 in segs:
                e = make_line(*tr(x1, y1), *tr(x2, y2), style)
                e["gen"] = "views"
                project.drawing.append(e)
                made += 1
        # Габаритные размеры: на главном виде — длина и высота, на виде сверху — ширина.
        dims = []
        x0, y0 = tr(b[0], b[1])
        x1, y1 = tr(b[2], b[3])
        if v == "front":
            dims += [make_dim(x0, y1, x1, y1, 10, "horizontal"), make_dim(x0, y0, x0, y1, -10, "vertical")]
        if v == "top":
            dims.append(make_dim(x0, y0, x0, y1, -10, "vertical"))
        for d in dims:
            d["gen"] = "views"
            d["k"] = 1 / scale  # размерное число — в натуральную величину
            project.drawing.append(d)
    return {"scale": label, "lines": made, "size": sheet_size(project.frame["format"], project.frame["orient"]), "iso": bool(axo)}


def _place_segments(project, segs, box, ox, oy, scale, gen, style="main") -> list[dict]:
    out = []
    for x1, y1, x2, y2 in segs:
        e = make_line(ox + (x1 - box[0]) * scale, oy + (y1 - box[1]) * scale, ox + (x2 - box[0]) * scale, oy + (y2 - box[1]) * scale, style)
        e["gen"] = gen
        out.append(e)
    project.drawing.extend(out)
    return out


def insert_axo(project, solid, kind: str = "iso", hidden: bool = False) -> dict:
    """Отдельный аксонометрический вид на лист: в правом верхнем углу рабочего поля, в масштабе листа (если не
    помещается — в ближайшем меньшем из ряда). Прежний такой вид заменяется. Возвращает {"lines", "scale", "box"}."""
    if solid.empty or solid.manifold is None:
        raise ValueError("нет тела: сначала постройте модель")
    if not project.frame:
        project.frame = default_frame()
    project.canvas = "sheet"
    vis, hid, box = axo_view(solid, kind, hidden=hidden)
    fx, fy, fw, fh = frame_rect(project.frame)
    top = fy + fh - 10.0
    room_w, room_h = fw - 20.0, fh - stamp_size(project.frame)[1] - 20.0
    w, h = box[2] - box[0], box[3] - box[1]
    cur = next((k for k, lab in SCALES if lab == project.frame.get("scale")), 1.0)
    scale, label = next(((k, lab) for k, lab in SCALES if k <= cur + 1e-12 and w * k <= room_w and h * k <= room_h), SCALES[-1])
    project.drawing[:] = [e for e in project.drawing if e.get("gen") != "axo"]
    ox, oy = fx + fw - 10.0 - w * scale, top - h * scale
    made = _place_segments(project, vis, box, ox, oy, scale, "axo") + _place_segments(project, hid, box, ox, oy, scale, "axo", "hidden")
    return {"lines": len(made), "scale": label, "box": (ox, oy, ox + w * scale, oy + h * scale), "kind": kind}
