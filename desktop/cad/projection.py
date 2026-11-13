"""Чертёж по 3D-модели: три стандартных вида (ГОСТ 2.305, метод первого угла) с невидимыми линиями.

Рёбра вида — острые рёбра сетки и силуэты (ребро между гранью к наблюдателю и гранью от него). Видимость —
лучом от точки ребра к наблюдателю: если луч упирается в тело, участок невидим (штриховая линия).
"""
from __future__ import annotations

import math

import numpy as np

from .model import default_frame, make_dim, make_line, sheet_size
from .stamp import H as STAMP_H
from .stamp import frame_rect

# Направление к наблюдателю и оси листа (вправо, вверх) для каждого вида.
VIEWS = {
    "front": (np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    "top": (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])),
    "left": (np.array([-1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
}
SCALES = [(10, "10:1"), (5, "5:1"), (4, "4:1"), (2.5, "2,5:1"), (2, "2:1"), (1, "1:1"), (0.5, "1:2"), (0.4, "1:2,5"),
          (0.25, "1:4"), (0.2, "1:5"), (0.1, "1:10"), (0.05, "1:20")]


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


def _visible(manifold, p, to_viewer, reach):
    hits = manifold.ray_cast((p + to_viewer * 0.02).tolist(), (p + to_viewer * reach).tolist())
    return not any(h.distance * reach > 0.03 for h in hits)


_NUDGE = 0.01   # мм: точку ребра чуть выносим наружу, чтобы луч не скользил по своей же грани


def project_view(solid, view: str, samples_per_mm: float = 0.6):
    """Видимые и невидимые отрезки вида в координатах листа (масштаб 1:1, без сдвига)."""
    to_viewer, ux, uy = VIEWS[view]
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
    xs = [lo @ ux, hi @ ux]
    ys = [lo @ uy, hi @ uy]
    box = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
    return vis2, hid2, box


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


def make_drawing(project, solid, gap: float = 30.0) -> dict:
    """Заменяет сгенерированные виды на листе: главный вид, вид сверху под ним, вид слева справа от него,
    габаритные размеры. Масштаб — ближайший стандартный, при котором виды помещаются над основной надписью."""
    if solid.empty or solid.manifold is None:
        raise ValueError("нет тела: сначала постройте модель")
    if not project.frame:
        project.frame = default_frame()
    views = {v: project_view(solid, v) for v in VIEWS}
    fx, fy, fw, fh = frame_rect(project.frame)
    area = (fx + 15, fy + STAMP_H + 15, fw - 30, fh - STAMP_H - 30)
    (_, _, bf), (_, _, bt), (_, _, bl) = views["front"], views["top"], views["left"]
    W = lambda b: b[2] - b[0]  # noqa: E731
    Hh = lambda b: b[3] - b[1]  # noqa: E731
    need_w = W(bf) + W(bl)
    need_h = Hh(bf) + Hh(bt)
    scale, label = next(((k, lab) for k, lab in SCALES if need_w * k + gap <= area[2] and need_h * k + gap <= area[3]), SCALES[-1])
    project.frame["scale"] = label
    # Расположение: главный вид слева сверху, вид слева — справа (та же высота), вид сверху — под главным.
    total_w, total_h = need_w * scale + gap, need_h * scale + gap
    left0 = area[0] + (area[2] - total_w) / 2
    top0 = area[1] + area[3] - (area[3] - total_h) / 2
    place = {
        "front": (left0, top0 - Hh(bf) * scale),
        "left": (left0 + W(bf) * scale + gap, top0 - Hh(bl) * scale),
        "top": (left0, top0 - Hh(bf) * scale - gap - Hh(bt) * scale),
    }
    project.drawing[:] = [e for e in project.drawing if e.get("gen") != "views"]
    made = 0
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
    return {"scale": label, "lines": made, "size": sheet_size(project.frame["format"], project.frame["orient"])}
