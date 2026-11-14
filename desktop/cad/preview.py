"""Векторное превью примитивов через QPainter: значки библиотеки, превью шаблона, «призрак» вставляемого элемента.

Рисует в мировых координатах (мм, ось Y вверх): вызывающий задаёт преобразование мм → пиксели. Перья косметические —
толщина в пикселях не зависит от масштаба значка.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform

from .dims import render
from .edit2d import hatch_segments
from .linestyles import shaped
from .model import arc_sweep
from .params import circle_axes

DASH = {"hidden": [4, 2], "axis": [8, 2, 1.5, 2], "fold": [8, 2, 1.5, 2, 1.5, 2]}


def _pen(color, width, style="main"):
    pen = QPen(color, width)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.RoundCap)
    if style in DASH:
        pen.setDashPattern(DASH[style])
    return pen


def draw_entities(p: QPainter, ents, color: QColor, main_px: float = 1.6, thin_px: float = 1.0):
    """Нарисовать примитивы текущим преобразованием painter (мм → пиксели, Y вверх)."""
    for e in ents:
        t, st = e["type"], e.get("style", "main")
        width = main_px if st == "main" else thin_px
        if t in ("line", "circle", "arc"):
            path = QPainterPath()
            parts = shaped(st, e["x1"], e["y1"], e["x2"], e["y2"]) if t == "line" else None
            if parts:
                for pts in parts:
                    path.moveTo(*pts[0])
                    for q in pts[1:]:
                        path.lineTo(*q)
            elif t == "line":
                path.moveTo(e["x1"], e["y1"])
                path.lineTo(e["x2"], e["y2"])
            elif t == "circle":
                path.addEllipse(QPointF(e["cx"], e["cy"]), e["r"], e["r"])
            else:
                r = e["r"]
                rect = QRectF(e["cx"] - r, e["cy"] - r, 2 * r, 2 * r)
                path.arcMoveTo(rect, -e["a0"])     # ось Y вверх: углы Qt со знаком минус
                path.arcTo(rect, -e["a0"], -arc_sweep(e))
            p.setPen(_pen(color, width, st))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(_pen(color, thin_px, "axis"))
            for x1, y1, x2, y2 in circle_axes(e):
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            continue
        p.setPen(_pen(color, thin_px))
        if t == "hatch":
            for x1, y1, x2, y2 in hatch_segments(e):
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            continue
        d = render(e)
        for x1, y1, x2, y2 in d.segs:
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        for tri in d.arrows:
            p.drawPolygon(QPolygonF([QPointF(*q) for q in tri]))
        p.setBrush(Qt.NoBrush)
        for x, y, h, s, ang, align in d.texts:
            draw_text(p, x, y, h, s, ang, align, color)


def draw_text(p: QPainter, x, y, h, s, ang, align, color):
    """Надпись высотой h мм: шрифт подбирается в пикселях экрана, чтобы мелкий текст не пропадал."""
    k = math.hypot(p.transform().m11(), p.transform().m12())   # пикселей на мм
    px = h * k * 1.43
    if px < 2.5:
        return
    p.save()
    p.translate(x, y)
    p.rotate(ang)
    p.scale(1 / k, -1 / k)    # дальше — пиксели, ось Y вниз
    f = QFont("Arial")
    f.setItalic(True)
    f.setPixelSize(max(1, round(px)))
    p.setFont(f)
    fm = p.fontMetrics()
    w = fm.horizontalAdvance(s)
    dx = {"center": -w / 2, "right": -w}.get(align, 0.0)
    p.setPen(QPen(color))
    p.drawText(QPointF(dx, 0), s)
    p.restore()


def fit_transform(bounds, rect: QRectF, margin: float = 0.08) -> QTransform:
    """мм → пиксели: габарит bounds (x0, y0, x1, y1) вписан в rect, ось Y вверх."""
    x0, y0, x1, y1 = bounds
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    inner = rect.adjusted(rect.width() * margin, rect.height() * margin, -rect.width() * margin, -rect.height() * margin)
    k = min(inner.width() / w, inner.height() / h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return QTransform(k, 0, 0, -k, inner.center().x() - cx * k, inner.center().y() + cy * k)


def render_pixmap(ents, size: int | tuple, color: QColor, bounds, extra=None, bg: QColor | None = None,
                  main_px: float = 1.6, thin_px: float = 1.0) -> QPixmap:
    """Значок: примитивы в квадрате size × size (или w × h). extra(p) — дорисовать (рамку листа) тем же преобразованием."""
    w, h = (size, size) if isinstance(size, int) else size
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)   # вдвое крупнее — чёткий значок на HiDPI
    img.fill(bg if bg is not None else Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setTransform(fit_transform(bounds, QRectF(0, 0, w * 2, h * 2)))
    if extra:
        extra(p)
    draw_entities(p, ents, color, main_px * 2, thin_px * 2)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(2.0)
    return pm
