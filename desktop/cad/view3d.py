"""3D-вьюпорт: pyqtgraph + OpenGL. Оси X/Y/Z, сетка, тело с рёбрами, вращение мышью,
навигационный гизмо в углу, перспективная и ортогональная проекция. Щелчок по грани — луч в сцену и ручка
прямого редактирования (cad.manip3d): стрелку тянут мышью, фантом показывает будущую форму."""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph.opengl as gl
from OpenGL import GL
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMatrix4x4, QPainter, QPen, QPolygonF, QVector3D
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from .dynhud import DynHud
from .geometry import Solid, feature_edges, ray_hit
from .manip3d import FaceManipulator, ghost_items
from .projection import DIM_ANGLES, ISO_ANGLES, dash_chains, edge_chains, view_edges


# Грани чуть отодвигаем по глубине, а рёбра рисуем с тестом глубины <=: так видны только рёбра на видимой стороне.
MESH_GL = {GL.GL_DEPTH_TEST: True, GL.GL_BLEND: False, GL.GL_CULL_FACE: False, GL.GL_POLYGON_OFFSET_FILL: True, "glPolygonOffset": (1.0, 1.0)}
EDGE_GL = {GL.GL_DEPTH_TEST: True, GL.GL_BLEND: True, "glBlendFunc": (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA), "glDepthFunc": (GL.GL_LEQUAL,)}

# Вид -> (азимут, возвышение) камеры pyqtgraph. Сверху и снизу — X вправо, как на чертеже.
VIEWS = {"iso": (-60, 28), "front": (-90, 0), "back": (90, 0), "right": (0, 0), "left": (180, 0),
         "top": (-90, 90), "bottom": (-90, -90),
         # аксонометрия ГОСТ 2.317: изометрия — оси под 120°, диметрия — оси x и z без сокращения, y — вдвое короче
         "iso_gost": ISO_ANGLES, "dim_gost": DIM_ANGLES}
GOST_VIEWS = ("iso_gost", "dim_gost")
DISPLAY = {"shaded": "Тонированный с рёбрами", "wire": "Каркас", "tech": "Технический изометрический чертёж"}
HIDDEN_GL = {GL.GL_DEPTH_TEST: True, GL.GL_BLEND: True, "glBlendFuncSeparate": (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA),
             "glDepthFunc": (GL.GL_GREATER,)}
DIM_GL = {GL.GL_DEPTH_TEST: False, GL.GL_BLEND: True, "glBlendFuncSeparate": (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)}


class HiddenLines(gl.GLLinePlotItem):
    """Невидимые рёбра: рисуются только там, где их заслоняет тело (тест глубины «дальше»), потом тест возвращается."""

    def paint(self):
        super().paint()
        GL.glDepthFunc(GL.GL_LESS)
VIEW_LABEL = {"front": "Спереди", "back": "Сзади", "right": "Справа", "left": "Слева", "top": "Сверху", "bottom": "Снизу"}
# Ось или нормаль грани куба -> вид, который открывает щелчок по ней (камера смотрит с этой стороны).
AXIS_VIEW = {(1, 0, 0): "right", (-1, 0, 0): "left", (0, 1, 0): "back", (0, -1, 0): "front", (0, 0, 1): "top", (0, 0, -1): "bottom"}
AXIS_COLOR = {0: "#e5484d", 1: "#30a46c", 2: "#3e7bfa"}


class NavGizmo(QWidget):
    """Гизмо ориентации в духе Blender: оси с шарами-кнопками и полупрозрачный куб, повёрнутые как сцена.
    Щелчок по шару или грани — плавный переход к ортогональному виду, перетаскивание — вращение орбиты."""

    SIZE = 124

    def __init__(self, view: "View3D"):
        super().__init__(view)
        self.view = view
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Щелчок — вид по оси или грани, перетаскивание — вращение")
        self._press: QPointF | None = None
        self._last: QPointF | None = None
        self._dragged = False
        self.hover: tuple | None = None

    # ---- геометрия гизмо в пикселях виджета
    def basis(self):
        """Экранные направления мировых осей: (вправо, вниз, к зрителю) — из той же матрицы, что у камеры."""
        m = QMatrix4x4()
        m.rotate(self.view.opts["elevation"] - 90, 1, 0, 0)
        m.rotate(self.view.opts["azimuth"] + 90, 0, 0, -1)
        out = []
        for w in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            v = m.mapVector(QVector3D(*w))
            out.append((v.x(), -v.y(), v.z()))
        return out

    def _pt(self, w, scale, b=None):
        b = b or self.basis()
        c = self.SIZE / 2
        x = sum(w[i] * b[i][0] for i in range(3))
        y = sum(w[i] * b[i][1] for i in range(3))
        z = sum(w[i] * b[i][2] for i in range(3))
        return QPointF(c + x * scale, c + y * scale), z

    def balls(self):
        """[(ось, центр, радиус, глубина)] — для отрисовки и попадания."""
        R, b = self.SIZE / 2 - 13, self.basis()
        out = []
        for i in range(3):
            for sign in (1, -1):
                w = tuple(sign if k == i else 0 for k in range(3))
                p, z = self._pt(w, R, b)
                out.append((w, p, 9.0 if sign > 0 else 7.0, z))
        return out

    def faces(self):
        """[(нормаль, многоугольник, глубина центра)] граней куба."""
        h, b = (self.SIZE / 2 - 13) * 0.42, self.basis()
        out = []
        for i in range(3):
            for sign in (1, -1):
                n = tuple(sign if k == i else 0 for k in range(3))
                a, c = [k for k in range(3) if k != i]
                quad = []
                for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    w = [0.0, 0.0, 0.0]
                    w[i], w[a], w[c] = sign, u, v
                    quad.append(self._pt(w, h, b)[0])
                out.append((n, QPolygonF(quad), self._pt(n, h, b)[1]))
        return out

    def hit(self, pos: QPointF):
        """Ось или грань под точкой: сначала ближние к зрителю."""
        for w, p, r, z in sorted(self.balls(), key=lambda t: -t[3]):
            if math.hypot(pos.x() - p.x(), pos.y() - p.y()) <= r + 2:
                return w
        for n, poly, z in sorted(self.faces(), key=lambda t: -t[2]):
            if z > 0.05 and poly.containsPoint(pos, Qt.OddEvenFill):
                return n
        return None

    # ---- отрисовка
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 30 if self.hover or self._dragged else 14))
        p.drawEllipse(c, self.SIZE / 2 - 1, self.SIZE / 2 - 1)
        items = [("face", n, poly, z) for n, poly, z in self.faces()] + [("ball", w, (pt, r), z) for w, pt, r, z in self.balls()]
        small = QFont("Segoe UI", 7)
        bold = QFont("Segoe UI", 7, QFont.Bold)
        for kind, key, geom, z in sorted(items, key=lambda t: t[3]):   # от дальних к ближним
            axis = next(i for i in range(3) if key[i])
            col = QColor(AXIS_COLOR[axis])
            hot = key == self.hover
            if kind == "face":
                p.setBrush(QColor(200, 212, 228, 120 if hot else 40 + int(45 * max(z, 0))))
                p.setPen(QPen(QColor(220, 228, 240, 150), 1))
                p.drawPolygon(geom)
                if z > 0.55:
                    p.setFont(small)
                    p.setPen(QColor(255, 255, 255, 225))
                    p.drawText(geom.boundingRect(), Qt.AlignCenter, VIEW_LABEL[AXIS_VIEW[key]])
                continue
            pt, r = geom
            positive = key[axis] > 0
            if positive:
                p.setPen(QPen(col, 2.2))
                p.drawLine(c, pt)
            p.setPen(QPen(col.lighter(140), 1.5) if hot else Qt.NoPen)
            p.setBrush(col if positive else QColor(col.red(), col.green(), col.blue(), 120))
            rr = r + (1.5 if hot else 0)
            p.drawEllipse(pt, rr, rr)
            if positive or hot:
                p.setFont(bold)
                p.setPen(QColor("#ffffff"))
                p.drawText(QRectF(pt.x() - 10, pt.y() - 10, 20, 20), Qt.AlignCenter, ("" if positive else "-") + "XYZ"[axis])
        p.end()

    # ---- мышь
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._press = self._last = ev.position()
            self._dragged = False

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._press is not None and ev.buttons() & Qt.LeftButton:
            if (pos - self._press).manhattanLength() > 3:
                self._dragged = True
            if self._dragged:
                d = pos - self._last
                self.view.stop_animation()
                self.view.orbit(-d.x() * 1.2, d.y() * 1.2)
            self._last = pos
        else:
            h = self.hit(pos)
            if h != self.hover:
                self.hover = h
                self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or self._press is None:
            return
        if not self._dragged:
            key = self.hit(ev.position())
            if key is not None:
                self.view.animate_to(AXIS_VIEW[key])
        self._press, self._dragged = None, False
        self.update()

    def leaveEvent(self, ev):
        self.hover = None
        self.update()


class View3D(gl.GLViewWidget):
    viewChanged = Signal()
    faceClicked = Signal(object)         # попадание луча {"point", "normal", "tri"} или None — щелчок мимо тела
    faceDoubleClicked = Signal(object)

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.ortho = False
        self._anim = QTimer(self)
        self._anim.setInterval(15)
        self._anim.timeout.connect(self._anim_step)
        self._anim_clock = QElapsedTimer()
        self._anim_from = self._anim_to = (0.0, 0.0)
        self.anim_ms = 280
        self.gizmo = NavGizmo(self)
        self.proj_btn = self._corner_btn("◩", "Перспектива / ортогональная проекция (5)", self.toggle_projection)
        self.proj_btn.setCheckable(True)
        self.home_btn = self._corner_btn("⌂", "Центрировать модель (Home)", self.home)
        self.setBackgroundColor((30, 35, 43))
        self.setCameraPosition(distance=220, elevation=28, azimuth=-60)
        self.grid = gl.GLGridItem()
        self.grid.setSize(400, 400)
        self.grid.setSpacing(10, 10)
        self.grid.setColor((80, 90, 104, 110))
        self.addItem(self.grid)
        self.body_rgb = np.array([0.74, 0.79, 0.86])
        self.edge_rgba = (0.05, 0.06, 0.08, 1.0)
        self._solid: Solid | None = None
        for vec, color in (((60, 0, 0), (0.94, 0.36, 0.36, 1)), ((0, 60, 0), (0.27, 0.76, 0.48, 1)), ((0, 0, 60), (0.3, 0.55, 1.0, 1))):
            self.addItem(gl.GLLinePlotItem(pos=np.array([(0, 0, 0), vec], float), color=color, width=3, antialias=True))
        self.mesh_item: gl.GLMeshItem | None = None
        self.edge_item: gl.GLLinePlotItem | None = None
        self.hidden_item: HiddenLines | None = None
        self.display = "shaded"              # shaded | wire | tech
        self.show_dims = False
        self.dims: list[dict] = []           # размеры на модели (projection.model_dims)
        self.dim_items: list = []
        self.dim_labels: list = []           # (надпись, точка в мире)
        self._tech_timer = QTimer(self)      # очерк и штрихи зависят от взгляда — пересчёт после остановки камеры
        self._tech_timer.setSingleShot(True)
        self._tech_timer.setInterval(70)
        self._tech_timer.timeout.connect(self._tech_refresh)
        self.hud = DynHud(self)              # бейдж «Глубина H: … мм» у курсора при перетаскивании стрелки
        self._mouse_pos = QPointF()
        self.theme = None
        self.manip = FaceManipulator(self)
        self.ghost: list = []
        self._press_pos: QPointF | None = None
        self._moved = False
        self.setMouseTracking(True)
        self.viewChanged.connect(self.manip.reposition)
        self.viewChanged.connect(lambda: self._tech_timer.start() if self.display == "tech" else None)
        self.manip.moved.connect(lambda v: self.hud.show_info(f"Глубина H: {v:.1f} мм", self._mouse_pos))
        self.manip.released.connect(lambda _v: self.hud.hide_info())
        self.manip.cancelled.connect(self.hud.hide_info)
        if theme is not None:
            self.apply_theme(theme)

    def apply_theme(self, theme, force: bool = True):
        """Фон, сетка, цвет тела и рёбер из темы (cad.themes.Theme). force=False — только если тема другая."""
        if not force and theme is self.theme:
            return
        self.theme = theme
        q = QColor(theme.view3d_bg)
        self.setBackgroundColor((q.red(), q.green(), q.blue()))
        g = QColor(theme.view3d_grid)
        self.grid.setColor((g.red(), g.green(), g.blue(), 160))
        b, e = QColor(theme.body), QColor(theme.edge)
        self.body_rgb = np.array([b.redF(), b.greenF(), b.blueF()])
        self.edge_rgba = (e.redF(), e.greenF(), e.blueF(), 1.0)
        self.manip.set_accent(theme.accent)
        if self._solid is not None:
            self.show_solid(self._solid)

    def show_solid(self, solid: Solid, fit: bool = False):
        self._solid = solid
        for it in (self.mesh_item, self.edge_item, self.hidden_item):
            if it is not None:
                self.removeItem(it)
        self.mesh_item = self.edge_item = self.hidden_item = None
        if solid.empty:
            self._draw_dims()
            return
        if self.display != "shaded":
            self._show_lines(solid)
            if fit:
                self.fit(solid)
            self._draw_dims()
            return
        # Освещение считаем сами (Ламберт + заполняющий свет): не зависит от шейдеров драйвера слабого ноутбука.
        v = solid.verts[solid.faces]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        key = np.clip(n @ np.array([0.35, -0.45, 0.82]), 0, 1)
        fill = np.clip(n @ np.array([-0.6, 0.5, 0.3]), 0, 1)
        k = (0.42 + 0.48 * key + 0.15 * fill)[:, None]
        colors = np.hstack([np.clip(k * self.body_rgb / 0.8, 0, 1), np.ones((len(k), 1))]).astype(np.float32)
        md = gl.MeshData(vertexes=solid.verts, faces=solid.faces, faceColors=colors)
        self.mesh_item = gl.GLMeshItem(meshdata=md, smooth=False, shader=None, glOptions=MESH_GL)
        self.addItem(self.mesh_item)
        edges = feature_edges(solid.verts, solid.faces)
        if len(edges):
            self.edge_item = gl.GLLinePlotItem(pos=edges, mode="lines", color=self.edge_rgba, width=1.5, antialias=True, glOptions=EDGE_GL)
            self.addItem(self.edge_item)
        if fit:
            self.fit(solid)
        self._draw_dims()

    # ---- режимы отображения: каркас и технический чертёж
    def set_display(self, mode: str):
        if mode not in DISPLAY:
            raise ValueError("отображение: " + ", ".join(DISPLAY))
        self.display = mode
        if self._solid is not None:
            self.show_solid(self._solid)
        self.update()

    def to_viewer(self) -> np.ndarray:
        p, c = self.cameraPosition(), self.opts["center"]
        v = np.array([p.x() - c.x(), p.y() - c.y(), p.z() - c.z()])
        return v / (np.linalg.norm(v) or 1.0)

    def ink(self) -> tuple:
        """Цвет линий технического вида: тёмный на светлом фоне, светлый на тёмном."""
        bg = QColor(self.theme.view3d_bg) if self.theme is not None else QColor(30, 35, 43)
        return (0.05, 0.06, 0.08, 1.0) if bg.lightness() > 128 else (0.93, 0.95, 0.98, 1.0)

    def _show_lines(self, solid: Solid):
        """Каркас — все рёбра без граней. Технический — грани цвета фона закрывают дальние рёбра: видимые рисуются
        сплошной толстой линией, невидимые — штриховой (ГОСТ 2.303)."""
        ink = self.ink()
        if self.display == "wire":
            edges = feature_edges(solid.verts, solid.faces)
            if len(edges):
                self.edge_item = gl.GLLinePlotItem(pos=edges, mode="lines", color=ink, width=1.6, antialias=True, glOptions=DIM_GL)
                self.addItem(self.edge_item)
            return
        bg = QColor(self.theme.view3d_bg) if self.theme is not None else QColor(30, 35, 43)
        md = gl.MeshData(vertexes=solid.verts, faces=solid.faces)
        self.mesh_item = gl.GLMeshItem(meshdata=md, color=(bg.redF(), bg.greenF(), bg.blueF(), 1.0), smooth=False, shader=None, glOptions=MESH_GL)
        self.addItem(self.mesh_item)
        self.tech_pairs = pairs = view_edges(solid, self.to_viewer())
        if not len(pairs):
            return
        seg = solid.verts[pairs.reshape(-1)].astype(float)
        self.edge_item = gl.GLLinePlotItem(pos=seg, mode="lines", color=ink, width=2.6, antialias=True, glOptions=EDGE_GL)
        self.edge_item.setDepthValue(1)
        self.addItem(self.edge_item)
        px = self.world_per_pixel()
        self.tech_dashes = dashes = dash_chains(solid.verts, edge_chains(pairs), 9 * px, 5 * px)
        if len(dashes):
            self.hidden_item = HiddenLines(pos=dashes, mode="lines", color=ink, width=1.2, antialias=True, glOptions=HIDDEN_GL)
            self.hidden_item.setDepthValue(2)
            self.addItem(self.hidden_item)

    def _tech_refresh(self):
        if self.display == "tech" and self._solid is not None and not self._solid.empty and not self.manip.dragging and not self.ghost:
            self.show_solid(self._solid)
            self.manip.reposition()

    # ---- размеры прямо на модели
    def set_dims(self, dims: list[dict], show: bool | None = None):
        self.dims = list(dims)
        if show is not None:
            self.show_dims = bool(show)
        self._draw_dims()

    def _draw_dims(self):
        for it in self.dim_items:
            self.removeItem(it)
        self.dim_items = []
        for lab, _ in self.dim_labels:
            lab.deleteLater()
        self.dim_labels = []
        if not self.show_dims or not self.dims:
            self.update()
            return
        accent = QColor(self.theme.accent) if self.theme is not None else QColor("#3e7bfa")
        rgba = (accent.redF(), accent.greenF(), accent.blueF(), 1.0)
        lines = []
        for d in self.dims:
            a, b = np.asarray(d["a"], float), np.asarray(d["b"], float)
            lines += [a, b]
            for p, q in d["ext"]:
                lines += [np.asarray(p, float), np.asarray(q, float)]
            u = (b - a) / (np.linalg.norm(b - a) or 1.0)
            n = np.cross(u, [0.0, 0.0, 1.0]) if abs(u[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
            ar = 0.035 * float(np.linalg.norm(b - a)) + 1.2
            for tip, sgn in ((a, 1.0), (b, -1.0)):          # стрелки на концах размерной линии
                for side in (1.0, -1.0):
                    lines += [tip, tip + sgn * u * ar + side * n * ar * 0.3]
        item = gl.GLLinePlotItem(pos=np.array(lines), mode="lines", color=rgba, width=1.6, antialias=True, glOptions=DIM_GL)
        item.setDepthValue(20)
        self.dim_items.append(item)
        for d in self.dims:      # числа — надписями поверх окна: читаются при любом повороте и не зависят от шейдеров
            lab = QLabel(d["text"], self)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lab.setStyleSheet(f"QLabel{{background:rgba(20,26,36,215);color:#ffffff;border:1px solid {accent.name()};"
                              "border-radius:4px;padding:1px 5px;font-weight:600}")
            lab.adjustSize()
            self.dim_labels.append((lab, np.asarray(d["at"], float)))
        for it in self.dim_items:
            self.addItem(it)
        self._place_dim_labels()
        self.update()

    def _place_dim_labels(self):
        for lab, at in self.dim_labels:
            p = self.project(at)
            if p is None:
                lab.hide()
                continue
            lab.move(int(p.x() - lab.width() / 2), int(p.y() - lab.height() / 2))
            lab.show()

    def dim_texts(self) -> list[str]:
        return [lab.text() for lab, _ in self.dim_labels]

    def fit(self, solid: Solid):
        lo, hi = solid.bbox()
        c = (lo + hi) / 2
        self.opts["center"] = QVector3D(float(c[0]), float(c[1]), float(c[2]))
        self.setCameraPosition(distance=float(np.linalg.norm(hi - lo)) * 1.8 + 30)

    def set_view(self, name: str):
        self.stop_animation()
        if name in GOST_VIEWS:
            self.set_ortho(True)      # аксонометрия — параллельная проекция
        az, el = VIEWS[name]
        self.setCameraPosition(elevation=el, azimuth=az)
        self.viewChanged.emit()

    # ---- гизмо, плавные переходы, проекция
    def _corner_btn(self, glyph, tip, slot):
        b = QToolButton(self)
        b.setText(glyph)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setFixedSize(28, 28)
        b.setFont(QFont("Segoe UI Symbol", 12))
        b.setStyleSheet("QToolButton{background:rgba(34,42,54,170);color:#f3f6fa;border:1px solid rgba(255,255,255,90);border-radius:6px}"
                        "QToolButton:hover{background:rgba(34,42,54,230)}QToolButton:checked{background:rgba(62,123,250,160)}")
        b.clicked.connect(slot)
        return b

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        x = self.width() - NavGizmo.SIZE - 10
        self.gizmo.move(x, 10)
        self.proj_btn.move(x - 34, 16)
        self.home_btn.move(x - 34, 50)

    def animate_to(self, name: str):
        """Плавный поворот камеры к виду по кратчайшему пути (азимут не крутится лишний оборот)."""
        if name in GOST_VIEWS:
            self.set_ortho(True)
        az0, el0 = self.opts["azimuth"], self.opts["elevation"]
        az1, el1 = VIEWS[name]
        az1 = az0 + ((az1 - az0 + 180) % 360 - 180)
        self._anim_from, self._anim_to = (az0, el0), (az1, el1)
        self._anim_clock.start()
        self._anim.start()
        self._anim_step()

    def _anim_step(self):
        t = min(1.0, self._anim_clock.elapsed() / self.anim_ms) if self.anim_ms > 0 else 1.0
        k = 1 - (1 - t) ** 3   # плавное торможение в конце
        (a0, e0), (a1, e1) = self._anim_from, self._anim_to
        self.setCameraPosition(azimuth=a0 + (a1 - a0) * k, elevation=e0 + (e1 - e0) * k)
        if t >= 1.0:
            self._anim.stop()
        self.viewChanged.emit()

    def animating(self) -> bool:
        return self._anim.isActive()

    def finish_animation(self):
        if self._anim.isActive():
            saved, self.anim_ms = self.anim_ms, 0
            self._anim_step()
            self.anim_ms = saved

    def stop_animation(self):
        self._anim.stop()

    def orbit(self, azim, elev):
        super().orbit(azim, elev)
        self.gizmo.update()
        self.viewChanged.emit()

    def setCameraPosition(self, *a, **kw):
        super().setCameraPosition(*a, **kw)
        if hasattr(self, "gizmo"):
            self.gizmo.update()

    def toggle_projection(self):
        self.set_ortho(not self.ortho)

    def set_ortho(self, on: bool):
        self.ortho = bool(on)
        self.proj_btn.setChecked(self.ortho)
        self.proj_btn.setText("▣" if self.ortho else "◩")
        self.update()
        self.viewChanged.emit()

    def projectionMatrix(self, region, viewport):
        if not self.ortho:
            return super().projectionMatrix(region, viewport)
        # Ортогональная проекция с тем же охватом, что у перспективы в центре сцены: колесо по-прежнему масштабирует.
        x0, y0, w, h = viewport
        dist = self.opts["distance"]
        r = dist * math.tan(0.5 * math.radians(self.opts["fov"]))
        t = r * h / w
        tr = QMatrix4x4()
        tr.ortho(r * ((region[0] - x0) * (2.0 / w) - 1), r * ((region[0] + region[2] - x0) * (2.0 / w) - 1),
                 t * ((region[1] - y0) * (2.0 / h) - 1), t * ((region[1] + region[3] - y0) * (2.0 / h) - 1),
                 -(dist * 20 + 1000), dist * 20 + 1000)   # и за камерой: при сильном приближении тело не срезается
        return tr

    def home(self):
        """Вписать модель (или пустую сцену) в окно и навести камеру на её центр."""
        self.stop_animation()
        if self._solid is not None and not self._solid.empty:
            self.fit(self._solid)
        else:
            self.opts["center"] = QVector3D(0, 0, 0)
            self.setCameraPosition(distance=220)
        self.viewChanged.emit()

    def point_under(self, pos) -> np.ndarray:
        """Мировая точка под пикселем pos в плоскости центра вращения (перпендикулярно взгляду)."""
        w, h = max(self.width(), 1), max(self.height(), 1)
        r = self.opts["distance"] * math.tan(0.5 * math.radians(self.opts["fov"]))   # полуширина, как в проекции
        nx, ny = 2 * pos.x() / w - 1, 1 - 2 * pos.y() / h
        m = self.viewMatrix()
        right = np.array([m.row(0).x(), m.row(0).y(), m.row(0).z()])
        up = np.array([m.row(1).x(), m.row(1).y(), m.row(1).z()])
        c = self.opts["center"]
        return np.array([c.x(), c.y(), c.z()]) + right * nx * r + up * ny * r * h / w

    def zoom_at(self, f: float, pos):
        """Дистанция ×f к точке под курсором: камера и центр подобно сжимаются к ней — точка не смещается
        на экране ни в перспективе, ни в ортогональной проекции, вид не дёргается в сторону."""
        d = self.opts["distance"] * f
        if not 0.05 < d < 1e6:
            return
        p = self.point_under(pos)
        c = self.opts["center"]
        c = np.array([c.x(), c.y(), c.z()]) + (p - np.array([c.x(), c.y(), c.z()])) * (1 - f)
        self.opts["center"] = QVector3D(*map(float, c))
        self.opts["distance"] = d
        self.update()
        self.viewChanged.emit()

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if ev.modifiers() & Qt.ControlModifier or not delta:
            super().wheelEvent(ev)   # Ctrl + колесо — угол обзора, как в pyqtgraph
            return
        self.stop_animation()
        self.zoom_at(0.999 ** delta, ev.position())
        ev.accept()

    # ---- луч из экрана, проекция в экран, фантом
    def _pv(self) -> np.ndarray:
        vp = self.getViewport()
        p = np.array(self.projectionMatrix(vp, vp).copyDataTo(), float).reshape(4, 4)
        v = np.array(self.viewMatrix().copyDataTo(), float).reshape(4, 4)
        return p @ v

    def ray(self, pos) -> tuple[np.ndarray, np.ndarray]:
        """Луч под пикселем pos: (начало на ближней плоскости, единичное направление) — и в перспективе, и в орто."""
        w, h = max(self.width(), 1), max(self.height(), 1)
        nx, ny = 2 * pos.x() / w - 1, 1 - 2 * pos.y() / h
        inv = np.linalg.inv(self._pv())
        a, b = inv @ np.array([nx, ny, -1.0, 1.0]), inv @ np.array([nx, ny, 1.0, 1.0])
        a, b = a[:3] / a[3], b[:3] / b[3]
        d = b - a
        return a, d / (np.linalg.norm(d) or 1.0)

    def project(self, p) -> QPointF | None:
        """Мировая точка → пиксель виджета (None — за камерой)."""
        c = self._pv() @ np.r_[np.asarray(p, float), 1.0]
        if c[3] <= 1e-9:
            return None
        n = c[:3] / c[3]
        return QPointF((n[0] + 1) / 2 * self.width(), (1 - n[1]) / 2 * self.height())

    def world_per_pixel(self) -> float:
        return 2 * self.opts["distance"] * math.tan(0.5 * math.radians(self.opts["fov"])) / max(self.height(), 1)

    def pick(self, pos):
        """Грань под курсором — сигнал faceClicked (с попаданием или None)."""
        hit = ray_hit(self._solid, *self.ray(pos)) if self._solid is not None and not self._solid.empty else None
        self.faceClicked.emit(hit)
        return hit

    def show_ghost(self, solid: Solid):
        """Фантом будущей формы вместо граней тела; рёбра нынешнего тела остаются как ориентир."""
        self.clear_ghost(restore=False)
        if self.mesh_item is not None:
            self.mesh_item.setVisible(False)
        self.ghost = ghost_items(solid, self.manip.accent)
        for it in self.ghost:
            self.addItem(it)
        self.update()

    def clear_ghost(self, restore: bool = True):
        for it in self.ghost:
            self.removeItem(it)
        self.ghost = []
        if restore and self.mesh_item is not None:
            self.mesh_item.setVisible(True)
        self.update()

    def paintGL(self, *a, **kw):
        super().paintGL(*a, **kw)
        self.manip.reposition()      # плашка размера — за концом стрелки при любом движении камеры
        self._place_dim_labels()

    # ---- мышь: стрелка манипулятора, щелчок по грани, иначе — вращение и сдвиг pyqtgraph
    def mousePressEvent(self, ev):
        pos = ev.position()
        self._press_pos, self._moved = None, False     # отпускание после стрелки или отмены — не щелчок по грани
        if self.manip.dragging and ev.button() == Qt.RightButton:
            self.manip.cancel()
            ev.accept()
            return
        if ev.button() == Qt.LeftButton and self.manip.hit(pos):
            self.manip.begin(pos)
            ev.accept()
            return
        self._press_pos = QPointF(pos)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        self._mouse_pos = QPointF(pos)
        if self.manip.dragging:
            self.manip.drag(pos, ev.modifiers())
            ev.accept()
            return
        if self._press_pos is not None and (pos - self._press_pos).manhattanLength() > 3:
            self._moved = True
        if not ev.buttons():
            self.setCursor(Qt.SizeVerCursor if self.manip.hit(pos) else Qt.ArrowCursor)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.manip.dragging and ev.button() == Qt.LeftButton:
            self.manip.end()
            self._press_pos = None
            ev.accept()
            return
        if ev.button() == Qt.LeftButton and self._press_pos is not None and not self._moved:
            self.pick(ev.position())
        self._press_pos = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if self.manip.handle is not None and self.manip.hit(ev.position()):
                self.manip.editRequested.emit()
            elif self._solid is not None and not self._solid.empty:
                self.faceDoubleClicked.emit(ray_hit(self._solid, *self.ray(ev.position())))
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and (self.manip.dragging or self.manip.handle is not None):
            if self.manip.dragging:
                self.manip.cancel()
            else:
                self.faceClicked.emit(None)
            return
        if ev.key() == Qt.Key_Home:
            self.home()
        elif ev.key() == Qt.Key_5:
            self.toggle_projection()
        else:
            super().keyPressEvent(ev)
