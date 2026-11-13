"""Локальный анализ фото и сканов перед отправкой ИИ: габарит и пропорции объекта, окружности (отверстия), дуги,
контрастные прямые, симметрия. Только numpy и Pillow, без OpenCV и сети.

Считается на уменьшенной копии (длинная сторона WORK px). Координаты в сводке — в долях габарита объекта: x слева
направо, y снизу вверх, 0..1; диаметры — в долях ширины объекта. Это подсказка к пропорциям и расположению, а не
измерение: перспектива снимка не учитывается, размеры в миллиметрах берутся из чисел на чертеже или из запроса.
"""
from __future__ import annotations

import math

import numpy as np

WORK = 480
ANG_BINS = 72                 # по 5° — проверка, что окружность замкнута


def analyze(im) -> dict:
    """PIL.Image → сводка (dict с числами, round до 3 знаков)."""
    g = _gray(im)
    res = _analyze(g)
    paper = res.pop("_paper", None)
    if paper is not None:                       # светлый прямоугольник на тёмном: лист с чертежом или сама деталь?
        y0, y1, x0, x1 = paper
        inner = _analyze(g[y0:y1, x0:x1], allow_paper=False)
        if inner.get("_line_art"):              # на нём линии — это лист: разбираем то, что на листе
            inner["лист_на_фото"] = {"рамка_в_кадре_%": _pct((x0, y0, x1, y1), g.shape)}
            res = inner
        else:                                   # на нём пятна-отверстия — это деталь
            res = _analyze(g, allow_paper=False)
    res.pop("_line_art", None)
    res["кадр_px"] = list(im.size)
    return res


def _gray(im) -> np.ndarray:
    from PIL import Image

    g = im.convert("L")
    k = WORK / max(g.size)
    if k < 1:
        g = g.resize((max(1, round(g.size[0] * k)), max(1, round(g.size[1] * k))), Image.BOX)
    return np.asarray(g, dtype=np.float32) / 255.0


def _analyze(g: np.ndarray, allow_paper: bool = True) -> dict:
    h, w = g.shape
    if h < 16 or w < 16:
        return {"ошибка": "изображение слишком маленькое для анализа"}
    blur = _box3(g)
    edge = 2
    border = np.concatenate([blur[:edge].ravel(), blur[-edge:].ravel(), blur[:, :edge].ravel(), blur[:, -edge:].ravel()])
    t = _otsu(blur)
    light_bg = float(np.median(border)) >= t
    fg = blur < t if light_bg else blur > t
    if fg.all() or not fg.any():
        return {"фон": "однородный", "контраст": 0.0, "тип": "пустой кадр — линий и предметов не видно"}
    contrast = float(abs(blur[fg].mean() - blur[~fg].mean()))
    comps = components(fg)
    big = max(comps, key=lambda c: c["area"])
    fill = big["area"] / max(1, (big["x1"] - big["x0"]) * (big["y1"] - big["y0"]))
    res = {"фон": "светлый" if light_bg else "тёмный", "контраст": round(contrast, 2)}
    bw0, bh0 = big["x1"] - big["x0"], big["y1"] - big["y0"]
    if allow_paper and not light_bg and fill > 0.85 and bw0 * bh0 > 0.25 * w * h and bw0 < w - 4 and bh0 < h - 4:
        mx, my = max(2, int(bw0 * 0.03)), max(2, int(bh0 * 0.03))
        res["_paper"] = (big["y0"] + my, big["y1"] - my, big["x0"] + mx, big["x1"] - mx)
        return res
    line_art = fill < 0.35
    res["_line_art"] = line_art
    if line_art:                                # чертёж: всё заметное, кроме пылинок
        least = max(6, 0.002 * int(fg.sum()))
        keep = [c for c in comps if c["area"] >= least]
    else:                                       # предмет: самое крупное пятно
        keep = [big]
    x0, y0 = min(c["x0"] for c in keep), min(c["y0"] for c in keep)
    x1, y1 = max(c["x1"] for c in keep), max(c["y1"] for c in keep)
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    res["тип"] = "чертёж или эскиз: линии на светлом фоне" if line_art and light_bg else (
        "линии на тёмном фоне" if line_art else "предмет на фоне (фото детали)")
    res["объект_в_кадре_%"] = _pct((x0, y0, x1, y1), g.shape)
    res["пропорции_ш_к_в"] = round(bw / bh, 3)
    box = (x0, y0, bw, bh)
    region = fg[y0:y1, x0:x1]
    if not line_art:                            # силуэт детали с дырами: отверстия тоже края
        region = _component_mask(fg, big)[y0:y1, x0:x1]
    res["симметрия"] = {"вертикальная_ось": _sym(region, 1), "горизонтальная_ось": _sym(region, 0)}

    gx, gy, mag = _sobel(blur)
    thr = max(0.08, 0.35 * float(np.percentile(mag, 99.5)))
    ys, xs = np.nonzero(mag > thr)
    rng = np.random.default_rng(7)
    kept = min(1.0, 14000 / max(1, xs.size))     # доля точек края после прореживания — для порога плотности
    if xs.size > 14000:
        pick = rng.choice(xs.size, 14000, replace=False)
        xs, ys = xs[pick], ys[pick]
    side = min(bw, bh)
    circles, arcs = _circles(xs, ys, gx, gy, mag, (h, w), rmin=max(3, int(0.012 * max(bw, bh))), rmax=max(6, int(0.55 * side)),
                             density=kept)
    res["окружности"] = [_norm_circle(c, box) for c in circles]
    res["дуги"] = [{**_norm_circle(a, box), "от_град": a["a0"], "до_град": a["a1"]} for a in arcs]
    res["массивы_отверстий"] = _patterns(circles, box)

    py, px = np.nonzero(fg) if line_art else (ys, xs)
    if px.size > 16000:
        pick = rng.choice(px.size, 16000, replace=False)
        px, py = px[pick], py[pick]
    px, py = px.astype(np.float32), py.astype(np.float32)
    free = ~on_curves(px, py, circles + arcs)          # хорды окружностей — не прямые
    lines = _lines(px[free], py[free], (h, w), min_len=max(10.0, 0.08 * side))
    hor = sum(1 for s in lines if s["ang"] < 3 or s["ang"] > 177)
    ver = sum(1 for s in lines if 87 < s["ang"] < 93)
    res["прямые"] = {"горизонтальных": hor, "вертикальных": ver, "наклонных": len(lines) - hor - ver,
                     "длинные": [_norm_line(s, box) for s in lines[:14]]}
    return res


# ---------------------------------------------------------------- сводка для промпта
def summary(res: dict) -> str:
    if "ошибка" in res or "объект_в_кадре_%" not in res:
        return "Локальный анализ: " + str(res.get("ошибка") or res.get("тип") or "нет данных")
    out = ["Локальный анализ изображения (оценка по пикселям; координаты в долях габарита объекта: x вправо, y вверх, 0..1; "
           "диаметры — в долях ширины объекта):"]
    if "лист_на_фото" in res:
        out.append(f"- на фото лист бумаги на тёмном фоне, он занимает {res['лист_на_фото']['рамка_в_кадре_%']} % кадра; ниже — то, что на листе")
    out.append(f"- {res['тип']}; фон {res['фон']}, контраст {res['контраст']}")
    l, t, r, b = res["объект_в_кадре_%"]
    out.append(f"- объект в кадре: x {l}–{r} %, y {t}–{b} % (сверху вниз); пропорции ширина : высота = {res['пропорции_ш_к_в']}")
    s = res["симметрия"]
    out.append(f"- симметрия: относительно вертикальной оси {s['вертикальная_ось']}, горизонтальной {s['горизонтальная_ось']} (1 — полная)")
    cs = res["окружности"]
    if cs:
        out.append(f"- окружностей {len(cs)}: " + "; ".join(f"центр ({c['x']}, {c['y']}) d {c['d']}" for c in cs[:12]))
    else:
        out.append("- замкнутых окружностей не найдено")
    for p in res["массивы_отверстий"]:
        out.append(f"- {p['число']} одинаковых окружностей d {p['d']} по окружности d {p['d_центров']} с центром ({p['x']}, {p['y']}), "
                   f"первая под {p['угол_первой']}°" + (", центр совпадает с центром крупной окружности" if p.get("соосно") else ""))
    if res["дуги"]:
        out.append(f"- дуг {len(res['дуги'])}: " + "; ".join(f"центр ({a['x']}, {a['y']}) R {round(a['d'] / 2, 3)} от {a['от_град']}° до {a['до_град']}°"
                                                            for a in res["дуги"][:8]))
    ln = res["прямые"]
    out.append(f"- прямых: горизонтальных {ln['горизонтальных']}, вертикальных {ln['вертикальных']}, наклонных {ln['наклонных']}")
    if ln["длинные"]:
        out.append("- самые длинные (x1, y1 → x2, y2; длина в долях ширины): " + "; ".join(
            f"({s['x1']}, {s['y1']} → {s['x2']}, {s['y2']}; {s['L']})" for s in ln["длинные"][:10]))
    return "\n".join(out)


# ---------------------------------------------------------------- примитивы обработки
def _box3(g):
    p = np.pad(g, 1, mode="edge")
    return sum(p[dy:dy + g.shape[0], dx:dx + g.shape[1]] for dy in range(3) for dx in range(3)) / 9.0


def _otsu(g) -> float:
    hist = np.bincount((np.clip(g, 0, 1) * 255).astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    p = hist / hist.sum()
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    sigma = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega) + 1e-12)
    return (int(np.argmax(sigma)) + 0.5) / 255.0


def _sobel(g):
    p = np.pad(g, 1, mode="edge")
    h, w = g.shape
    s = lambda dy, dx: p[dy:dy + h, dx:dx + w]  # noqa: E731
    gx = (s(0, 2) + 2 * s(1, 2) + s(2, 2)) - (s(0, 0) + 2 * s(1, 0) + s(2, 0))
    gy = (s(2, 0) + 2 * s(2, 1) + s(2, 2)) - (s(0, 0) + 2 * s(0, 1) + s(0, 2))
    return gx, gy, np.hypot(gx, gy)


def _maxfilter(a, k):
    r = k // 2
    out = a.copy()
    p = np.pad(a, ((0, 0), (r, r)), mode="constant", constant_values=-np.inf)
    for d in range(k):
        np.maximum(out, p[:, d:d + a.shape[1]], out=out)
    p = np.pad(out, ((r, r), (0, 0)), mode="constant", constant_values=-np.inf)
    res = out.copy()
    for d in range(k):
        np.maximum(res, p[d:d + a.shape[0]], out=res)
    return res


def _dilate(mask, r=1):
    return _maxfilter(mask.astype(np.float32), 2 * r + 1) > 0


def components(mask: np.ndarray) -> list[dict]:
    """Связные области (8-связность) по отрезкам строк — без scipy: площадь, рамка [x0, x1), [y0, y1), отрезки."""
    h, w = mask.shape
    pad = np.zeros((h, w + 2), np.int8)
    pad[:, 1:-1] = mask
    d = np.diff(pad, axis=1)
    parent: list[int] = []
    runs: list[tuple] = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    prev: list[tuple] = []
    for y in range(h):
        starts = np.flatnonzero(d[y] == 1).tolist()
        ends = np.flatnonzero(d[y] == -1).tolist()
        cur, j = [], 0
        for x0, x1 in zip(starts, ends):
            idx = len(runs)
            parent.append(idx)
            runs.append((y, x0, x1))
            while j < len(prev) and prev[j][1] < x0:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] <= x1:
                ra, rb = find(idx), find(prev[k][2])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
                k += 1
            cur.append((x0, x1, idx))
        prev = cur
    comps: dict[int, dict] = {}
    for i, (y, x0, x1) in enumerate(runs):
        c = comps.setdefault(find(i), {"area": 0, "x0": x0, "x1": x1, "y0": y, "y1": y + 1, "runs": []})
        c["area"] += x1 - x0
        c["x0"], c["x1"] = min(c["x0"], x0), max(c["x1"], x1)
        c["y1"] = y + 1
        c["runs"].append((y, x0, x1))
    return list(comps.values())


def _component_mask(shape_src, comp):
    m = np.zeros(shape_src.shape, bool)
    for y, x0, x1 in comp["runs"]:
        m[y, x0:x1] = True
    return m


def _sym(region, axis) -> float:
    if region.size == 0 or not region.any():
        return 0.0
    m = _dilate(region, 1)
    f = m[:, ::-1] if axis == 1 else m[::-1, :]
    return round(float((m & f).sum() / max(1, (m | f).sum())), 2)


def _circles(xs, ys, gx, gy, mag, shape, rmin, rmax, density=1.0):
    """Окружности по градиенту (Хаф: центр — на нормали к краю), проверка замкнутости по секторам 5°.
    Дуги (от 90°) ищутся вторым проходом — по точкам, которые не легли на найденные окружности."""
    h, w = shape
    if xs.size < 20 or rmax <= rmin:
        return [], []
    m = mag[ys, xs]
    ux, uy = gx[ys, xs] / m, gy[ys, xs] / m
    acc = np.zeros(h * w, np.float64)
    xf, yf = xs.astype(np.float32), ys.astype(np.float32)
    for r0 in range(rmin, rmax + 1, 24):
        rr = np.arange(r0, min(rmax + 1, r0 + 24), dtype=np.float32)
        for sign in (1.0, -1.0):
            cx = np.rint(xf[:, None] + sign * ux[:, None] * rr[None, :]).astype(np.int32)
            cy = np.rint(yf[:, None] + sign * uy[:, None] * rr[None, :]).astype(np.int32)
            ok = (cx >= 0) & (cx < w) & (cy >= 0) & (cy < h)
            acc += np.bincount((cy[ok] * w + cx[ok]), minlength=h * w)
    acc = _box3(acc.reshape(h, w).astype(np.float32))
    py, px = np.nonzero((acc == _maxfilter(acc, 9)) & (acc >= 6))
    centers = []
    for i in np.argsort(-acc[py, px])[:60]:
        cx, cy = float(px[i]), float(py[i])
        y0, y1, x0, x1 = max(0, int(cy) - 1), min(h, int(cy) + 2), max(0, int(cx) - 1), min(w, int(cx) + 2)
        win = acc[y0:y1, x0:x1]                                # центр — по весам накопителя 3×3
        if win.sum() > 0:
            gy_, gx_ = np.mgrid[y0:y1, x0:x1]
            cx, cy = float((gx_ * win).sum() / win.sum()), float((gy_ * win).sum() / win.sum())
        centers.append((cx, cy))
    nr = rmax - rmin + 1

    def rings(cx, cy, keep):
        x, y = xf[keep], yf[keep]
        ri = np.rint(np.hypot(x - cx, y - cy)).astype(np.int32) - rmin
        ok = (ri >= 0) & (ri < nr)
        ab = ((np.arctan2(-(y - cy), x - cx) % (2 * math.pi)) / (2 * math.pi) * ANG_BINS).astype(np.int32) % ANG_BINS
        ri, ab = ri[ok], ab[ok]
        occ = np.bincount(ri * ANG_BINS + ab, minlength=nr * ANG_BINS).reshape(nr, ANG_BINS) > 0
        band = occ.copy()
        band[1:] |= occ[:-1]
        band[:-1] |= occ[1:]
        cnt = np.bincount(ri, minlength=nr).astype(np.float32)
        dens = (cnt + np.r_[0, cnt[:-1]] + np.r_[cnt[1:], 0]) / (2 * math.pi * (np.arange(nr) + rmin))
        return band, band.sum(1) / ANG_BINS, dens, ri, ab

    everything = np.ones(xf.size, bool)
    circles = []
    for cx, cy in centers:
        band, cover, dens, _, _ = rings(cx, cy, everything)
        taken = []
        for k in np.argsort(-cover):
            if cover[k] < 0.78 or len(taken) >= 3:
                break
            if all(abs(k - t) >= 5 for t in taken) and dens[k] >= 0.5 * density:
                circles.append({"cx": cx, "cy": cy, "r": float(k + rmin), "score": float(cover[k])})
                taken.append(k)
    circles = _dedupe(circles, 16)
    rest = ~on_curves(xf, yf, circles)
    arcs = []
    if rest.sum() >= 20:
        for cx, cy in centers:
            band, cover, dens, ri, ab = rings(cx, cy, rest)
            for k in np.argsort(-cover)[:3]:
                r = float(k + rmin)
                if cover[k] < 0.25 or cover[k] >= 0.78 or r < 5:
                    continue
                start, run = _longest_run(band[k])
                on_arc = np.isin(ab, (np.arange(start, start + run) % ANG_BINS)) & (np.abs(ri - k) <= 1)
                arc_dens = on_arc.sum() / max(1.0, r * run * 2 * math.pi / ANG_BINS)
                if run >= ANG_BINS // 4 and arc_dens >= 1.5 * density and run >= 0.8 * cover[k] * ANG_BINS:
                    a0 = start * 360 // ANG_BINS
                    arcs.append({"cx": cx, "cy": cy, "r": r, "score": float(arc_dens), "a0": a0, "a1": (a0 + run * 360 // ANG_BINS) % 360})
    return circles, _dedupe(arcs, 8, against=circles)


def on_curves(x, y, curves, tol=3.5):
    """Точки, лежащие на окружностях или дугах (с толщиной штриха)."""
    hit = np.zeros(x.size, bool)
    for c in curves:
        hit |= np.abs(np.hypot(x - c["cx"], y - c["cy"]) - c["r"]) <= tol
    return hit


def _longest_run(row):
    """(начало, длина) самой длинной серии занятых секторов по кругу."""
    if row.all():
        return 0, len(row)
    n = len(row)
    best, start = (0, 0), None
    for i in range(2 * n):
        if row[i % n]:
            if start is None:
                start = i
            if i - start + 1 > best[1] and i - start + 1 <= n:
                best = (start % n, i - start + 1)
        else:
            start = None
    return best


def _dedupe(items, limit, against=()):
    out = []
    for c in sorted(items, key=lambda c: (-c["score"], -c["r"])):
        if any(math.hypot(c["cx"] - o["cx"], c["cy"] - o["cy"]) < max(3, 0.15 * c["r"]) and abs(c["r"] - o["r"]) < max(4, 0.12 * c["r"])
               for o in [*out, *against]):
            continue
        out.append(c)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda c: (-c["r"], c["cy"], c["cx"]))


def _lines(xs, ys, shape, min_len):
    """Отрезки по Хафу: пик накопителя → точки у прямой → непрерывные участки без разрывов больше gap."""
    h, w = shape
    if xs.size < 10:
        return []
    th = np.deg2rad(np.arange(180, dtype=np.float32))
    cos, sin = np.cos(th), np.sin(th)
    diag = int(math.ceil(math.hypot(w, h)))
    nr = 2 * diag + 1
    rho = np.rint(xs[:, None] * cos[None, :] + ys[:, None] * sin[None, :]).astype(np.int32) + diag
    acc = np.bincount((np.arange(180, dtype=np.int32)[None, :] * nr + rho).ravel(), minlength=180 * nr).reshape(180, nr).astype(np.float32)
    gap = max(3.0, 0.015 * diag)
    alive = np.ones(xs.size, bool)
    out = []
    for _ in range(120):
        k = int(acc.argmax())
        if acc.flat[k] < 0.7 * min_len or len(out) >= 40:
            break
        ti, ri = divmod(k, nr)
        c, s, r = float(cos[ti]), float(sin[ti]), float(ri - diag)
        dist = np.abs(xs * c + ys * s - r)
        near = alive & (dist <= 1.5)
        t_all = -xs * s + ys * c
        t = np.sort(t_all[near])
        found = []
        if t.size >= 2:
            cuts = np.flatnonzero(np.diff(t) > gap)
            for a, b in zip(np.r_[0, cuts + 1], np.r_[cuts, t.size - 1]):
                length = float(t[b] - t[a])
                if length >= min_len and (b - a + 1) >= 0.5 * length:
                    found.append((float(t[a]), float(t[b])))
        # голоса забираем у точек отрезков вместе с толщиной штриха; без отрезка — у точек на прямой
        if found:
            gone = alive & (dist <= 3.0) & np.any([(t_all >= a - 1) & (t_all <= b + 1) for a, b in found], axis=0)
        else:
            gone = near
        if not gone.any():
            acc.flat[k] = 0
            continue
        rr = np.rint(xs[gone, None] * cos[None, :] + ys[gone, None] * sin[None, :]).astype(np.int32) + diag
        acc -= np.bincount((np.arange(180, dtype=np.int32)[None, :] * nr + rr).ravel(), minlength=180 * nr).reshape(180, nr)
        alive &= ~gone
        for a, b in found:
            p1 = (r * c - a * s, r * s + a * c)
            p2 = (r * c - b * s, r * s + b * c)
            ang = math.degrees(math.atan2(-(p2[1] - p1[1]), p2[0] - p1[0])) % 180
            out.append({"x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1], "len": b - a, "ang": ang})
    return sorted(out, key=lambda s: -s["len"])


def _patterns(circles, box):
    """Группы одинаковых окружностей, лежащих по окружности (отверстия фланца)."""
    out = []
    pool = sorted(circles, key=lambda c: c["r"])
    used = set()
    for i, c in enumerate(pool):
        if i in used:
            continue
        grp = [j for j, o in enumerate(pool) if j not in used and abs(o["r"] - c["r"]) <= max(1.5, 0.15 * c["r"])]
        if len(grp) < 3:
            continue
        pts = np.array([[pool[j]["cx"], pool[j]["cy"]] for j in grp])
        ctr = pts.mean(0)
        rad = np.hypot(*(pts - ctr).T)
        if rad.mean() < 2 * c["r"] or rad.std() > 0.08 * rad.mean():
            continue
        used.update(grp)
        x0, y0, bw, bh = box
        angs = np.degrees(np.arctan2(-(pts[:, 1] - ctr[1]), pts[:, 0] - ctr[0])) % 360
        big = [o for o in circles if o["r"] > 1.5 * c["r"] and math.hypot(o["cx"] - ctr[0], o["cy"] - ctr[1]) < max(3, 0.1 * rad.mean())]
        out.append({"число": len(grp), "d": round(2 * c["r"] / bw, 3), "d_центров": round(2 * float(rad.mean()) / bw, 3),
                    "x": round((float(ctr[0]) - x0) / bw, 3), "y": round((y0 + bh - float(ctr[1])) / bh, 3),
                    "угол_первой": round(float(angs.min()), 1), "соосно": bool(big)})
    return out


def _norm_circle(c, box):
    x0, y0, bw, bh = box
    return {"x": round(float(c["cx"] - x0) / bw, 3), "y": round(float(y0 + bh - c["cy"]) / bh, 3), "d": round(float(2 * c["r"]) / bw, 3)}


def _norm_line(s, box):
    x0, y0, bw, bh = box
    return {"x1": round(float(s["x1"] - x0) / bw, 3), "y1": round(float(y0 + bh - s["y1"]) / bh, 3),
            "x2": round(float(s["x2"] - x0) / bw, 3), "y2": round(float(y0 + bh - s["y2"]) / bh, 3), "L": round(float(s["len"]) / bw, 3)}


def _pct(rect, shape):
    x0, y0, x1, y1 = rect
    h, w = shape
    return [round(100 * x0 / w, 1), round(100 * y0 / h, 1), round(100 * x1 / w, 1), round(100 * y1 / h, 1)]
