"""Экспорт листа чертежа и эскиза в DXF (R12, кириллица через ANSI_1251) и SVG.

Типы линий по ГОСТ 2.303 — отдельные слои с типами линий DXF; размеры, штриховки и штамп — из тех же функций,
что рисуют экран (dims.render, edit2d.hatch_segments, stamp.frame_geometry).
"""
from __future__ import annotations

import math

from .dims import render
from .edit2d import hatch_segments
from .geometry import tessellate_arc
from .linestyles import DXF_LTYPE, STYLE_SPEC, wavy_points
from .model import arc_sweep, sheet_size
from .params import circle_axes
from .stamp import frame_geometry

LAYER = {"main": "MAIN", "thin": "THIN", "hidden": "HIDDEN", "axis": "AXIS", "fold": "FOLD", "wavy": "WAVY"}


def _items(project, entities, with_frame):
    """Всё, что нужно нарисовать: (вид, данные). Вид: line / circle / arc / poly / solid / text."""
    for e in entities:
        st = e.get("style", "main")
        t = e["type"]
        if t == "line":
            if st == "wavy":
                yield "poly", (wavy_points(e["x1"], e["y1"], e["x2"], e["y2"]), st)
            else:
                yield "line", ((e["x1"], e["y1"], e["x2"], e["y2"]), st)
        elif t == "circle":
            yield "circle", ((e["cx"], e["cy"], e["r"]), st)
            for sg in circle_axes(e):
                yield "line", (sg, "axis")
        elif t == "arc":
            yield "arc", ((e["cx"], e["cy"], e["r"], e["a0"], e["a1"]), st)
        elif t == "hatch":
            for sg in hatch_segments(e):
                yield "line", (sg, "thin")
        else:
            d = render(e)
            for sg in d.segs:
                yield "line", (sg, "thin")
            for tri in d.arrows:
                yield "solid", (tri, "thin")
            for x, y, h, s, ang, align in d.texts:
                yield "text", ((x, y, h, s, ang, align), "thin")
    if with_frame and project.sheet():
        lines, texts = frame_geometry(project.frame, project)
        for x1, y1, x2, y2, kind in lines:
            yield "line", ((x1, y1, x2, y2), "main" if kind == "main" else "thin")
        for x, y, h, s, align in texts:
            yield "text", ((x, y, h, s, 0.0, align), "thin")


# ---------------------------------------------------------------- DXF
def to_dxf(project, entities=None, with_frame=True) -> bytes:
    entities = project.drawing if entities is None else entities
    out: list[str] = []

    def add(*pairs):
        for code, value in pairs:
            out.append(str(code))
            out.append(str(value))

    def f(v):
        return f"{v:.6f}".rstrip("0").rstrip(".")

    add((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1009"), (9, "$DWGCODEPAGE"), (3, "ANSI_1251"),
        (9, "$INSUNITS"), (70, 4), (9, "$LTSCALE"), (40, 1.0), (0, "ENDSEC"))
    ltypes = {"CONTINUOUS": ("Solid", []), "HIDDEN": ("Hidden __ __", STYLE_SPEC["hidden"][1]),
              "CENTER": ("Center ____ . ____", STYLE_SPEC["axis"][1]), "PHANTOM": ("Phantom ____ . . ____", STYLE_SPEC["fold"][1])}
    add((0, "SECTION"), (2, "TABLES"), (0, "TABLE"), (2, "LTYPE"), (70, len(ltypes)))
    for name, (desc, pattern) in ltypes.items():
        add((0, "LTYPE"), (2, name), (70, 0), (3, desc), (72, 65), (73, len(pattern)), (40, f(sum(pattern))))
        for i, v in enumerate(pattern):
            add((49, f(v if i % 2 == 0 else -v)))
    add((0, "ENDTAB"), (0, "TABLE"), (2, "LAYER"), (70, len(LAYER)))
    colors = {"main": 7, "thin": 8, "hidden": 5, "axis": 1, "fold": 6, "wavy": 3}
    for st, name in LAYER.items():
        add((0, "LAYER"), (2, name), (70, 0), (62, colors[st]), (6, DXF_LTYPE[st]))
    add((0, "ENDTAB"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"))

    for kind, (data, st) in _items(project, entities, with_frame):
        lay = LAYER[st]
        if kind == "line":
            x1, y1, x2, y2 = data
            add((0, "LINE"), (8, lay), (10, f(x1)), (20, f(y1)), (30, 0), (11, f(x2)), (21, f(y2)), (31, 0))
        elif kind == "poly":
            for (a, b), (c, d) in zip(data, data[1:]):
                add((0, "LINE"), (8, lay), (10, f(a)), (20, f(b)), (30, 0), (11, f(c)), (21, f(d)), (31, 0))
        elif kind == "circle":
            cx, cy, r = data
            add((0, "CIRCLE"), (8, lay), (10, f(cx)), (20, f(cy)), (30, 0), (40, f(r)))
        elif kind == "arc":
            cx, cy, r, a0, a1 = data
            add((0, "ARC"), (8, lay), (10, f(cx)), (20, f(cy)), (30, 0), (40, f(r)), (50, f(a0)), (51, f(a1)))
        elif kind == "solid":
            (ax, ay), (bx, by), (cx, cy) = data
            add((0, "SOLID"), (8, lay), (10, f(ax)), (20, f(ay)), (30, 0), (11, f(bx)), (21, f(by)), (31, 0),
                (12, f(cx)), (22, f(cy)), (32, 0), (13, f(cx)), (23, f(cy)), (33, 0))
        elif kind == "text":
            x, y, h, s, ang, align = data
            add((0, "TEXT"), (8, lay), (10, f(x)), (20, f(y)), (30, 0), (40, f(h)), (1, s), (50, f(ang)))
            if align != "left":
                add((72, 1 if align == "center" else 2), (11, f(x)), (21, f(y)), (31, 0))
    add((0, "ENDSEC"), (0, "EOF"))
    return ("\r\n".join(out) + "\r\n").encode("cp1251", errors="replace")


# ---------------------------------------------------------------- SVG
def drawing_bounds(project, entities, with_frame=True) -> tuple[float, float, float, float]:
    if with_frame and project.sheet():
        w, h = sheet_size(project.frame["format"], project.frame.get("orient", "landscape"))
        return project.frame["x"], project.frame["y"], project.frame["x"] + w, project.frame["y"] + h
    xs, ys = [], []
    for kind, (data, _) in _items(project, entities, False):
        if kind == "line":
            xs += [data[0], data[2]]
            ys += [data[1], data[3]]
        elif kind in ("circle", "arc"):
            xs += [data[0] - data[2], data[0] + data[2]]
            ys += [data[1] - data[2], data[1] + data[2]]
        elif kind in ("poly", "solid"):
            xs += [p[0] for p in data]
            ys += [p[1] for p in data]
        elif kind == "text":
            xs.append(data[0])
            ys.append(data[1])
    if not xs:
        return 0, 0, 100, 100
    return min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5


def to_svg(project, entities=None, bounds=None, with_frame=True) -> str:
    entities = project.drawing if entities is None else entities
    x0, y0, x1, y1 = bounds or drawing_bounds(project, entities, with_frame)
    w, h = x1 - x0, y1 - y0
    Y = lambda y: y1 - y + y0  # noqa: E731 — переворот оси Y в пределах листа
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}">',
             '<g fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round">']

    def st_attr(st):
        width, dash = STYLE_SPEC[st]
        return f'stroke-width="{width:.2f}"' + (f' stroke-dasharray="{" ".join(f"{d:g}" for d in dash)}"' if dash else "")

    for kind, (data, st) in _items(project, entities, with_frame):
        a = st_attr(st)
        if kind == "line":
            parts.append(f'<line x1="{data[0]:.3f}" y1="{Y(data[1]):.3f}" x2="{data[2]:.3f}" y2="{Y(data[3]):.3f}" {a}/>')
        elif kind == "poly":
            parts.append('<polyline points="' + " ".join(f"{x:.3f},{Y(y):.3f}" for x, y in data) + f'" {a}/>')
        elif kind == "circle":
            parts.append(f'<circle cx="{data[0]:.3f}" cy="{Y(data[1]):.3f}" r="{data[2]:.3f}" {a}/>')
        elif kind == "arc":
            cx, cy, r, a0, a1 = data
            sweep = arc_sweep({"a0": a0, "a1": a1})
            sx, sy = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
            ex, ey = cx + r * math.cos(math.radians(a0 + sweep)), cy + r * math.sin(math.radians(a0 + sweep))
            if sweep >= 359.999:
                pts = tessellate_arc({"cx": cx, "cy": cy, "r": r, "a0": a0, "a1": a1})
                parts.append('<polyline points="' + " ".join(f"{x:.3f},{Y(y):.3f}" for x, y in pts) + f'" {a}/>')
            else:
                parts.append(f'<path d="M{sx:.3f} {Y(sy):.3f} A{r:.3f} {r:.3f} 0 {1 if sweep > 180 else 0} 0 {ex:.3f} {Y(ey):.3f}" {a}/>')
        elif kind == "solid":
            parts.append('<polygon points="' + " ".join(f"{x:.3f},{Y(y):.3f}" for x, y in data) + '" fill="#000" stroke="none"/>')
        elif kind == "text":
            x, y, hh, s, ang, align = data
            anchor = {"center": "middle", "right": "end"}.get(align, "start")
            s = s.replace("&", "&amp;").replace("<", "&lt;")
            parts.append(f'<text x="{x:.3f}" y="{Y(y):.3f}" font-size="{hh * 1.4:.2f}" font-family="GOST type A, Arial, sans-serif" font-style="italic" '
                         f'text-anchor="{anchor}" fill="#000" stroke="none" transform="rotate({-ang:.2f} {x:.3f} {Y(y):.3f})">{s}</text>')
    parts.append("</g></svg>")
    return "\n".join(parts)
