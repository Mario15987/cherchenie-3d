"""Прямое редактирование в 3D, как в КОМПАС-3D: выбранная грань подсвечивается, вдоль её нормали — стрелка
выдавливания и плашка с размером («H: 25.0 мм»). Стрелку тянут мышью: луч из-под курсора — ближайшая точка на оси
грани — новое значение; модель показывает фантом. Отпустили — значение уходит в операцию, двойной щелчок по
плашке — точный ввод. Все грани с ручками горизонтальны (выдавливание идёт по Z), поэтому ось стрелки — +Z.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from OpenGL import GL
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

# Стрелка и плашка видны всегда, даже за телом; подсветка грани — поверх своей грани (тело отодвинуто offset'ом).
# Альфа кадра остаётся 1 (glBlendFuncSeparate): иначе Qt смешает полупрозрачный кадр OpenGL с окном и исказит цвет.
BLEND = {GL.GL_BLEND: True, "glBlendFuncSeparate": (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)}
ARROW_GL = {GL.GL_DEPTH_TEST: False, **BLEND, GL.GL_CULL_FACE: False}
FACE_GL = {GL.GL_DEPTH_TEST: True, **BLEND, "glDepthFunc": (GL.GL_LEQUAL,), GL.GL_CULL_FACE: False}
GHOST_GL = {GL.GL_DEPTH_TEST: True, **BLEND, "glDepthFunc": (GL.GL_LEQUAL,), GL.GL_CULL_FACE: True}
LABEL = {"height": "H", "depth": "Глубина"}
GRAB_PX = 10.0           # насколько близко к стрелке на экране — она «под курсором»


class ValueBadge(QWidget):
    """Плашка с размером у конца стрелки: полупрозрачная, двойной щелчок — точное значение, тянуть — как стрелку."""

    def __init__(self, manip: "FaceManipulator"):
        super().__init__(manip.view)
        self.manip = manip
        self.text = ""
        self.accent = QColor("#3e7bfa")
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Тяните — изменить размер (Shift — шаг 0,1 мм), двойной щелчок — точное значение")
        self.hide()

    def set_text(self, text: str):
        self.text = text
        fm = self.fontMetrics()
        self.resize(fm.horizontalAdvance(text) + 18, fm.height() + 10)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(20, 26, 36, 205)
        p.setBrush(bg)
        p.setPen(QPen(self.accent, 1.5))
        p.drawRoundedRect(QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5), 5, 5)
        p.setPen(QColor("#ffffff"))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, self.text)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.manip.begin(self.mapTo(self.manip.view, ev.position().toPoint()))
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self.manip.dragging:
            pos = QPointF(self.mapTo(self.manip.view, ev.position().toPoint()))
            self.manip.view._mouse_pos = pos
            self.manip.drag(pos, ev.modifiers())

    def mouseReleaseEvent(self, ev):
        if self.manip.dragging:
            self.manip.end()

    def mouseDoubleClickEvent(self, ev):
        self.manip.cancel()
        self.manip.editRequested.emit()


class FaceManipulator(QWidget):
    """Не рисуется сам: держит GL-объекты стрелки и подсветки, плашку и состояние перетаскивания (QWidget — ради сигналов)."""
    moved = Signal(float)        # новое значение при перетаскивании
    released = Signal(float)     # значение зафиксировано
    cancelled = Signal()
    editRequested = Signal()

    def __init__(self, view):
        super().__init__(view)
        self.hide()
        self.view = view
        self.handle: dict | None = None
        self.base = np.zeros(3)          # точка грани, откуда растёт стрелка
        self.length = 20.0
        self.items: list = []
        self.badge = ValueBadge(self)
        self.accent = QColor("#3e7bfa")
        self.dragging = False
        self.value = 0.0
        self._v0 = 0.0
        self._t0 = 0.0
        self._press = QPointF()
        self._fallback = False
        self._tris = np.zeros(0, np.int64)
        self._solid = None

    # ---------------------------------------------------------------- показать / убрать
    def set_accent(self, color):
        self.accent = QColor(color)
        self.badge.accent = self.accent
        if self.handle is not None and not self.dragging:
            self._draw()

    def attach(self, handle: dict, solid, tris, anchor):
        """Ручка операции на грани tris тела solid; anchor — точка грани (там, где щёлкнули)."""
        self.handle = dict(handle)
        self._solid, self._tris = solid, np.asarray(tris)
        self.value = float(handle["value"])
        lo, hi = solid.bbox()
        self.length = float(np.clip(0.22 * np.linalg.norm(hi - lo), 6.0, 150.0))
        self.base = np.array([float(anchor[0]), float(anchor[1]), float(handle["z"])])
        self._draw()
        self.badge.set_text(self.text())
        self.badge.show()
        self.reposition()

    def detach(self):
        if self.dragging:
            self.cancel()
        self._clear()
        self.handle = None
        self.badge.hide()

    def text(self, value=None) -> str:
        v = self.value if value is None else value
        return f"{LABEL.get(self.handle['param'], self.handle['param'])}: {v:.1f} мм" if self.handle else ""

    def _clear(self):
        for it in self.items:
            self.view.removeItem(it)
        self.items = []

    def _rgba(self, a=1.0):
        c = self.accent
        return (c.redF(), c.greenF(), c.blueF(), a)

    def _draw(self, face_dz: float = 0.0):
        """Подсветка грани (сдвинутая на face_dz при перетаскивании), ось, стрелка с конусом и шарик-основание."""
        self._clear()
        if self.handle is None:
            return
        solid = self._solid
        if solid is not None and len(self._tris):
            verts = solid.verts.astype(np.float32).copy()
            faces = solid.faces[self._tris]
            used = np.unique(faces)
            verts[used, 2] += face_dz
            face = gl.GLMeshItem(meshdata=gl.MeshData(vertexes=verts, faces=faces), color=self._rgba(0.38), smooth=False,
                                 shader=None, glOptions=FACE_GL)
            face.setDepthValue(5)
            self.items.append(face)
        b = self.base + np.array([0, 0, face_dz])
        tip = b + np.array([0.0, 0.0, self.length])
        axis = gl.GLLinePlotItem(pos=np.array([b - [0, 0, self.length * 0.6], tip]), color=self._rgba(0.35), width=1.0,
                                 antialias=True, glOptions=ARROW_GL)
        shaft = gl.GLLinePlotItem(pos=np.array([b, tip]), color=self._rgba(1.0), width=4.0, antialias=True, glOptions=ARROW_GL)
        head_len, head_r = self.length * 0.22, self.length * 0.08
        cone = gl.MeshData.cylinder(rows=1, cols=24, radius=[head_r, 0.0], length=head_len)
        head = gl.GLMeshItem(meshdata=cone, color=self._rgba(1.0), smooth=False, shader=None, glOptions=ARROW_GL)
        head.translate(*tip)
        knob = gl.GLMeshItem(meshdata=gl.MeshData.sphere(rows=8, cols=12, radius=self.length * 0.04), color=self._rgba(0.9),
                             smooth=False, shader=None, glOptions=ARROW_GL)
        knob.translate(*b)
        for it in (axis, shaft, head, knob):
            it.setDepthValue(10)
            self.items.append(it)
        for it in self.items:
            self.view.addItem(it)

    def reposition(self):
        """Плашка — у конца стрелки на экране (после каждого кадра: вращение, зум, сдвиг)."""
        if self.handle is None:
            return
        tip = self.view.project(self.tip())
        if tip is None:
            self.badge.hide()
            return
        self.badge.move(int(tip.x() + 12), int(tip.y() - self.badge.height() - 6))
        self.badge.show()
        self.badge.raise_()

    # ---------------------------------------------------------------- геометрия на экране
    def face_dz(self) -> float:
        return self.handle["dir"] * (self.value - float(self.handle["value"])) if self.handle else 0.0

    def base_point(self) -> np.ndarray:
        return self.base + np.array([0.0, 0.0, self.face_dz()])

    def tip(self) -> np.ndarray:
        return self.base_point() + np.array([0.0, 0.0, self.length * 1.22])

    def screen_segment(self):
        a, b = self.view.project(self.base_point()), self.view.project(self.tip())
        return (a, b) if a is not None and b is not None else None

    def hit(self, pos) -> bool:
        """Курсор на стрелке (отрезок от основания до конца конуса на экране) или на плашке."""
        if self.handle is None:
            return False
        if self.badge.isVisible() and self.badge.geometry().contains(QPointF(pos).toPoint()):
            return True
        seg = self.screen_segment()
        if seg is None:
            return False
        a, b = np.array([seg[0].x(), seg[0].y()]), np.array([seg[1].x(), seg[1].y()])
        p = np.array([pos.x(), pos.y()])
        ab = b - a
        t = float(np.clip(np.dot(p - a, ab) / (np.dot(ab, ab) or 1.0), 0, 1))
        return float(np.linalg.norm(p - (a + t * ab))) <= GRAB_PX

    def _axis_t(self, pos) -> float | None:
        """Параметр вдоль +Z ближайшей к лучу из курсора точки оси грани (None — смотрим вдоль оси)."""
        o, r = self.view.ray(pos)
        n = np.array([0.0, 0.0, 1.0])
        w = o - self.base
        rn = float(r @ n)
        den = 1.0 - rn * rn
        if den < 1e-4:
            return None
        return float((w @ n - (w @ r) * rn) / den)

    # ---------------------------------------------------------------- перетаскивание
    def begin(self, pos):
        if self.handle is None:
            return
        self.dragging = True
        self._v0 = self.value
        self._press = QPointF(pos)
        t = self._axis_t(QPointF(pos))
        self._fallback = t is None
        self._t0 = 0.0 if t is None else t

    def drag(self, pos, mods=Qt.NoModifier) -> float:
        """Новое значение по положению курсора: шаг 1 мм, с Shift — 0,1 мм; не меньше шага."""
        if not self.dragging:
            return self.value
        if self._fallback:   # вид строго вдоль оси: вверх по экрану — к зрителю
            dz = -(pos.y() - self._press.y()) * self.view.world_per_pixel()
        else:
            t = self._axis_t(QPointF(pos))
            dz = 0.0 if t is None else t - self._t0
        step = 0.1 if mods & Qt.ShiftModifier else 1.0
        value = self._v0 + self.handle["dir"] * dz
        return self.set_value(max(step, round(round(value / step) * step, 4)))   # 24.2, а не 24.200000000000003

    def set_value(self, value: float) -> float:
        """Значение при перетаскивании (и программно — из автотестов): стрелка, грань и плашка следуют."""
        if not self.dragging:
            self.dragging = True
            self._v0 = self.value
        value = float(value)
        if abs(value - self.value) > 1e-9:
            self.value = value
            self._draw(self.face_dz())
            self.badge.set_text(self.text())
            self.reposition()
            self.view.update()
            self.moved.emit(value)
        return self.value

    def end(self):
        if not self.dragging:
            return
        self.dragging = False
        changed = abs(self.value - self._v0) > 1e-9
        self.view.clear_ghost()
        if changed:
            self.released.emit(self.value)
        else:
            self._draw()

    def cancel(self):
        if not self.dragging:
            return
        self.dragging = False
        self.value = self._v0
        self.view.clear_ghost()
        self._draw()
        self.badge.set_text(self.text())
        self.reposition()
        self.cancelled.emit()

    def drag_to(self, value: float) -> float:
        """Программный вызов манипулятора: «перетащить» к значению и отпустить (автотесты, самопроверка)."""
        self.set_value(value)
        v = self.value
        self.end()
        return v


def ghost_items(solid, accent: QColor) -> list:
    """Фантом будущей формы: полупрозрачное тело цвета выделения и его рёбра."""
    from .geometry import feature_edges

    if solid is None or solid.empty:
        return []
    v = solid.verts[solid.faces]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    k = (0.55 + 0.4 * np.clip(n @ np.array([0.35, -0.45, 0.82]), 0, 1))[:, None]
    rgb = np.array([accent.redF(), accent.greenF(), accent.blueF()])
    colors = np.hstack([np.clip(k * (0.45 + 0.55 * rgb), 0, 1), np.full((len(k), 1), 0.55)]).astype(np.float32)
    mesh = gl.GLMeshItem(meshdata=gl.MeshData(vertexes=solid.verts, faces=solid.faces, faceColors=colors), smooth=False,
                         shader=None, glOptions=GHOST_GL)
    mesh.setDepthValue(3)
    out = [mesh]
    edges = feature_edges(solid.verts, solid.faces)
    if len(edges):
        line = gl.GLLinePlotItem(pos=edges, mode="lines", color=(rgb[0], rgb[1], rgb[2], 1.0), width=2.0, antialias=True,
                                 glOptions=FACE_GL)
        line.setDepthValue(4)
        out.append(line)
    return out
