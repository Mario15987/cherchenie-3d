"""2D-эскиз и лист чертежа на QGraphicsView: сетка, объектные привязки с маркерами, инструменты черчения,
редактирования и оформления, двойной щелчок по размеру или штампу."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from . import edit2d
from . import geometry as geo
from . import library
from . import params
from . import selection
from .dims import pick_distance, render
from .dynhud import DynHud
from .linestyles import shaped
from .model import (
    CURVES, arc_sweep, make_angdim, make_arc, make_circle, make_diadim, make_dim, make_hatch, make_leader, make_line,
    make_raddim, make_rect, make_rough, sheet_size,
)
from .stamp import frame_geometry, hit_cell

TOOLS = {
    "select": "Выбор: щёлкните объект (Shift — несколько). Двойной щелчок — свойства. Delete — удалить",
    "line": "Отрезок: начало и конец (или точные значения в панели). Цепочка продолжается; ПКМ или Esc — закончить",
    "rect": "Прямоугольник: два противоположных угла или X, Y, ширина, высота в панели",
    "circle": "Окружность: центр и точка на окружности или центр и радиус в панели",
    "arc": "Дуга: центр, начало и конец (против часовой стрелки)",
    "axis": "Осевая линия: две точки",
    "dim_h": "Горизонтальный размер: две точки, затем положение размерной линии",
    "dim_v": "Вертикальный размер: две точки, затем положение размерной линии",
    "dim_a": "Параллельный размер: две точки, затем положение размерной линии",
    "dim_dia": "Диаметр: щёлкните окружность, затем направление полки",
    "dim_rad": "Радиус: щёлкните дугу или окружность, затем направление",
    "dim_ang": "Угловой размер: первый отрезок, второй отрезок, затем положение дуги",
    "leader": "Выноска: точка стрелки, затем излом; текст — в панели",
    "rough": "Шероховатость: точка на поверхности; значение — в панели",
    "hatch": "Штриховка: щёлкните внутри замкнутого контура; вид, шаг и угол — в панели",
    "trim": "Усечь: щёлкните участок кривой, который нужно убрать",
    "extend": "Удлинить: щёлкните отрезок или дугу у конца, который нужно продлить",
    "chamfer": "Фаска: первый отрезок, затем второй (щёлкайте по сторонам, которые остаются)",
    "fillet": "Скругление: первый отрезок, затем второй",
    "mirror": "Симметрия: выделите объекты, затем укажите две точки оси",
    "pattern_lin": "Массив по сетке: выделите объекты и нажмите «Применить» в панели",
    "pattern_circ": "Массив по окружности: выделите объекты, затем укажите центр",
    "offset": "Эквидистанта: щёлкните кривую, затем сторону смещения",
    "frame": "Рамка: укажите левый нижний угол листа",
    "block": "Вставка элемента: щелчок — поставить; R или Пробел — повернуть на 90°; Ctrl+колесо — масштаб; Esc — закончить",
}
DRAW_TOOLS = ("line", "rect", "circle", "arc", "axis")
SNAP_KINDS = {"end": "Конец", "mid": "Середина", "center": "Центр", "intersection": "Пересечение",
              "perp": "Перпендикуляр", "tangent": "Касательная", "grid": "Сетка"}
_LABEL_KIND = {"конец": "end", "начало координат": "end", "середина": "mid", "центр": "center", "квадрант": "center", "пересечение": "intersection"}

DEFAULT_COLORS = {
    "paper1": "#fbfbf8", "paper2": "#fbfbf8", "grid_minor": "#e7ebee", "grid_major": "#cbd3da",
    "axis_x": "#d64545", "axis_y": "#2f9a5a", "ink": "#14181e", "dim": "#14181e", "select": "#e08a00", "preview": "#1f6fe0",
}
INFINITE = 100_000.0   # мм: «бесконечное» полотно — 200 м в каждую сторону, прокрутке не мешает
DASH = {"hidden": [6, 3], "axis": [14, 3, 2, 3], "fold": [14, 3, 2, 3, 2, 3], "axis_thick": [6, 2.5, 1.2, 2.5]}  # в толщинах пера (экранные пиксели)


def _pen(color: QColor, width_px: float, dash=None) -> QPen:
    p = QPen(color, width_px)
    p.setCosmetic(True)  # толщина в пикселях экрана при любом масштабе
    p.setCapStyle(Qt.RoundCap)
    if dash:
        p.setDashPattern(dash)
    return p


def style_pen(style: str, color: QColor, selected=False, k: float = 1.0) -> QPen:
    """k — толщина основной линии s относительно 0,5 мм (ГОСТ 2.303): все линии листа толще во столько же раз."""
    w = {"main": 2.0, "hidden": 1.4, "fold": 1.4, "axis_thick": 1.5, "open": 3.0}.get(style, 1.0) * k + (0.6 if selected else 0)
    return _pen(color, w, DASH.get(style))


COS30, SIN30 = math.cos(math.radians(30)), 0.5
ISO_AXES = ((COS30, SIN30, "30°"), (0.0, 1.0, "90°"), (-COS30, SIN30, "150°"))


def copy_of(e: dict) -> dict:
    import copy

    return copy.deepcopy(e)


class SketchView(QGraphicsView):
    cursorMoved = Signal(float, float, str)
    editStarted = Signal()        # перед правкой: снимок для отмены
    edited = Signal()             # после правки: обновить дерево, 3D, панели
    editFailed = Signal()         # правка не удалась: снимок для отмены не нужен
    selectionChanged = Signal(list)
    hint = Signal(str)
    live = Signal(dict)           # текущие значения инструмента — для панели точного ввода
    editEntity = Signal(str)      # двойной щелчок по объекту
    stampField = Signal(str)      # двойной щелчок по графе штампа
    contextRequested = Signal(QPoint)   # ПКМ по выделенному: редактор у курсора (экранная точка)
    toolEnded = Signal()          # ПКМ во время черчения: команда завершена, снова «Выбор»

    def __init__(self, project, layer: str = "sketch", parent=None, theme=None):
        super().__init__(parent)
        self.project = project
        self.layer = layer                    # sketch — профили для 3D, drawing — лист чертежа
        self.target_override: list | None = None   # эскиз операции, открытый на редактирование
        self.scene_ = QGraphicsScene(self)
        self.scene_.setSceneRect(-INFINITE, -INFINITE, 2 * INFINITE, 2 * INFINITE)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        # Точку под курсором держим сами (zoom_at): AnchorUnderMouse берёт её из mouseMoveEvent базового класса,
        # а движение мыши здесь обрабатывается без него — масштаб уезжал к устаревшей точке, в угол окна.
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setTransform(QTransform.fromScale(4, -4))  # 4 пикселя на мм, ось Y вверх
        self.centerOn(60, 40)

        self.tool = "select"
        self.style = "main"                   # тип линии для новых объектов
        self.params = {"chamfer_d1": 2.0, "chamfer_d2": 2.0, "chamfer_angle": 0.0, "fillet_r": 5.0, "offset_d": 5.0,
                       "offset_whole": True, "hatch_pattern": "metal", "hatch_step": 2.0, "hatch_angle": 45.0,
                       "leader_text": "1", "rough_value": "3,2", "rough_param": "Ra", "mirror_keep": True,
                       "pat_nx": 3, "pat_ny": 1, "pat_dx": 20.0, "pat_dy": 20.0, "pat_count": 6, "pat_angle": 360.0,
                       "blk_id": "", "blk_rot": 0.0, "blk_scale": 1.0, "blk_label": "", "circle_axes": False}
        self._drag: dict | None = None        # перетаскивание характерной точки
        self._box: dict | None = None         # рамка выделения
        self._move: dict | None = None        # перенос выделенной группы мышью
        self.selected: list[str] = []
        self.points: list[tuple[float, float]] = []
        self.picked: list[tuple[str, tuple[float, float]]] = []   # (id, точка щелчка) для инструментов по объектам
        self.cursor: tuple[float, float] | None = None
        self.snap_label = ""
        self.snap_kind = ""
        self.snaps = set(SNAP_KINDS)
        self._snap_cache: list[tuple[float, float, str]] = []
        self._pan: QPointF | None = None
        self.iso = False                      # изометрическая сетка 30° / 90° / 150° и черчение вдоль её осей
        self._mouse: QPointF | None = None    # курсор в пикселях виджета — туда ставится бейдж
        self._hud_msg = ""                    # что показать при перетаскивании точки или переносе
        self.hud = DynHud(self.viewport())
        self.hud.committed.connect(self._hud_commit)
        self.hud.cancelled.connect(self.setFocus)
        self.theme = theme                    # тема из ThemeManager; без неё — классические светлые цвета
        self.col = {k: QColor(getattr(theme, k) if theme else v) for k, v in DEFAULT_COLORS.items()}
        self.rebuild()

    # ------------------------------------------------------------ данные
    def target(self) -> list[dict]:
        if self.target_override is not None:
            return self.target_override
        return self.project.entities if self.layer == "sketch" else self.project.drawing

    def apply_theme(self, theme, force: bool = True):
        """Цвета из темы. force=False — только если тема поменялась (дёшево звать при каждом переключении)."""
        if not force and theme is self.theme:
            return
        self.theme = theme
        self.col = {k: QColor(getattr(theme, k)) for k in DEFAULT_COLORS}
        self.rebuild()

    # ------------------------------------------------------------ масштаб
    def px(self) -> float:
        return 1.0 / abs(self.transform().m11())

    def grid_step(self) -> float:
        for step in (1.0, 5.0, 10.0, 50.0, 100.0, 500.0):
            if step / self.px() >= 7:
                return step
        return 1000.0

    def sheet_bounds(self) -> QRectF | None:
        """Лист в мм на сцене — только у листа чертежа в режиме «лист»; на фрагменте и в эскизе — None."""
        fr = self.project.sheet() if self.layer == "drawing" else None
        if not fr:
            return None
        w, h = sheet_size(fr["format"], fr["orient"])
        return QRectF(fr["x"], fr["y"], w, h)

    def _limit_scroll(self):
        """На листе прокрутка ограничена листом с полями, на фрагменте — нет. Поле — почти окно: при отдалении
        сцена не становится уже окна (иначе Qt центрирует её и точка под курсором уезжает), зум в любой точке
        листа держит её под курсором, а от листа в окне всегда остаётся хотя бы полоска в 24 px."""
        s = self.sheet_bounds()
        if s is None:
            r = QRectF(-INFINITE, -INFINITE, 2 * INFINITE, 2 * INFINITE)
        else:
            m, px = max(s.width(), s.height()) * 0.6, self.px()
            mx, my = max(m, (self.viewport().width() - 24) * px), max(m, (self.viewport().height() - 24) * px)
            r = s.adjusted(-mx, -my, mx, my)
        if self.sceneRect() != r:
            self.setSceneRect(r)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._limit_scroll()

    def to_scene(self, pos: QPointF) -> QPointF:
        """Мировая точка под пикселем окна, без округления до целого пикселя."""
        return self.viewportTransform().inverted()[0].map(QPointF(pos))

    def scroll_by(self, dx: float, dy: float):
        """Сдвинуть изображение на (dx, dy) пикселей. Целая часть — полосами прокрутки, дробная — сдвигом
        в матрице вида: точка под курсором стоит на месте с точностью до долей пикселя."""
        self._limit_scroll()
        t = self.transform()
        tx, ty = t.dx() + dx, t.dy() + dy
        ix, iy = round(tx), round(ty)
        self.setTransform(QTransform(t.m11(), 0, 0, t.m22(), tx - ix, ty - iy))
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() - ix)
        v.setValue(v.value() - iy)

    def zoom_at(self, k: float, pos: QPointF) -> bool:
        """Масштаб k вокруг пикселя pos: мировая точка под курсором остаётся под курсором."""
        s = abs(self.transform().m11())
        if not 0.05 < s * k < 400:
            return False
        anchor = self.to_scene(pos)
        t = self.transform()
        self.setTransform(QTransform(t.m11() * k, 0, 0, t.m22() * k, t.dx(), t.dy()))
        self._limit_scroll()
        d = QPointF(pos) - self.viewportTransform().map(anchor)
        self.scroll_by(d.x(), d.y())
        self.viewport().update()
        return True

    def fit_sheet(self):
        """Вписать лист в окно (на фрагменте — всё, что начерчено)."""
        s = self.sheet_bounds()
        if s is None:
            self.fit_all()
            return
        self.fitInView(s.adjusted(-8, -8, 8, 8), Qt.KeepAspectRatio)
        t = self.transform()
        self.setTransform(QTransform.fromScale(abs(t.m11()), -abs(t.m22())))
        self._limit_scroll()   # поля прокрутки зависят от масштаба
        self.centerOn(s.center())

    def fit_all(self):
        rect = self.scene_.itemsBoundingRect()
        if rect.isEmpty():
            rect = QRectF(-10, -10, 140, 100)
        self.fitInView(rect.adjusted(-15, -15, 15, 15), Qt.KeepAspectRatio)
        t = self.transform()
        self.setTransform(QTransform.fromScale(abs(t.m11()), -abs(t.m22())))
        self._limit_scroll()
        self.centerOn(rect.center())

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120 or ev.angleDelta().x() / 120
        if steps and self.tool == "block" and ev.modifiers() & Qt.ControlModifier:
            self.scale_block(1.1 ** steps)    # Ctrl + колесо при вставке — масштаб элемента
        elif steps:
            self.zoom_at(1.2 ** steps, ev.position())   # тачпад шлёт доли щелчка — масштаб плавный
        ev.accept()

    # ------------------------------------------------------------ сцена
    def rebuild(self):
        self.scene_.clear()
        for e in self.target():
            self._add_entity(e, e["id"] in self.selected)
        self._limit_scroll()
        if self.sheet_bounds() is not None:
            lines, texts = frame_geometry(self.project.frame, self.project)
            for x1, y1, x2, y2, kind in lines:
                self.scene_.addLine(x1, y1, x2, y2, _pen(self.col["ink"], 2.0 if kind == "main" else 1.0)).setZValue(-1)
            for x, y, h, s, align in texts:
                self._add_text(x, y, h, s, 0.0, align, self.col["ink"])
        if self._drag is None and self._move is None:   # при перетаскивании — привязка только к чужим точкам
            self._snap_cache = geo.snap_points([e for e in self.target() if e["type"] in CURVES])
        self.viewport().update()

    def _add_path(self, path, pen, eid=None):
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        if eid:
            item.setData(0, eid)
        self.scene_.addItem(item)

    def _add_entity(self, e: dict, selected: bool):
        t = e["type"]
        if t in CURVES:
            color = self.col["select"] if selected else (self.col["dim"] if e["style"] == "thin" else self.col["ink"])
            path = QPainterPath()
            parts = shaped(e["style"], e["x1"], e["y1"], e["x2"], e["y2"]) if t == "line" else None
            if parts:
                for pts in parts:
                    path.moveTo(*pts[0])
                    for p in pts[1:]:
                        path.lineTo(*p)
            elif t == "line":
                path.moveTo(e["x1"], e["y1"])
                path.lineTo(e["x2"], e["y2"])
            elif t == "circle":
                path.addEllipse(QPointF(e["cx"], e["cy"]), e["r"], e["r"])
            else:
                r = e["r"]
                rect = QRectF(e["cx"] - r, e["cy"] - r, 2 * r, 2 * r)
                path.arcMoveTo(rect, -e["a0"])  # ось Y экрана перевёрнута — знак углов Qt обратный
                path.arcTo(rect, -e["a0"], -arc_sweep(e))
            self._add_path(path, style_pen(e["style"], color, selected, self.line_k()), e["id"])
            axes = params.circle_axes(e)
            if axes:
                ap = QPainterPath()
                for x1, y1, x2, y2 in axes:
                    ap.moveTo(x1, y1)
                    ap.lineTo(x2, y2)
                self._add_path(ap, style_pen("axis", self.col["select"] if selected else self.col["dim"]))
            return
        color = self.col["select"] if selected else self.col["dim"]
        pen = _pen(color, 1.3 if selected else 1.0)
        if t == "hatch":
            path = QPainterPath()
            for x1, y1, x2, y2 in edit2d.hatch_segments(e):
                path.moveTo(x1, y1)
                path.lineTo(x2, y2)
            self._add_path(path, pen, e["id"])
            return
        d = render(e)
        path = QPainterPath()
        for x1, y1, x2, y2 in d.segs:
            path.moveTo(x1, y1)
            path.lineTo(x2, y2)
        self._add_path(path, pen, e["id"])
        for tri in d.arrows:
            self.scene_.addPolygon(QPolygonF([QPointF(*p) for p in tri]), QPen(Qt.NoPen), QBrush(color))
        for x, y, h, s, ang, align in d.texts:
            self._add_text(x, y, h, s, ang, align, color)

    def line_k(self) -> float:
        return min(2.8, max(1.0, float(self.project.eskd.get("s", 0.5)) / 0.5))

    def _add_text(self, x, y, h, s, ang, align, color):
        t = QGraphicsSimpleTextItem(s)
        f = QFont("Arial")
        f.setItalic(bool(self.project.eskd.get("slant", True)))   # ГОСТ 2.304: с наклоном около 75° или прямой
        if self.project.eskd.get("font") == "A":                  # тип А — буквы уже (толщина линии h/14)
            f.setStretch(86)
        f.setPointSizeF(max(h * 1.07, 0.5))  # высота прописных ≈ h мм
        t.setFont(f)
        t.setBrush(QBrush(color))
        br = t.boundingRect()
        dx = {"center": -br.width() / 2, "right": -br.width()}.get(align, 0.0)
        t.setTransform(QTransform().translate(x, y).rotate(ang).scale(1, -1).translate(dx, -br.height() * 0.8))
        self.scene_.addItem(t)

    # ------------------------------------------------------------ привязки
    def snap(self, x: float, y: float) -> tuple[float, float, str, str]:
        tol = 10 * self.px()
        best, bd = None, tol
        for px_, py_, label in self._snap_cache:
            kind = _LABEL_KIND.get(label, "end")
            if kind in self.snaps:
                d = math.hypot(px_ - x, py_ - y)
                if d < bd - (0.3 * tol if kind in ("end", "intersection", "center") else 0):
                    best, bd = (px_, py_, label, kind), d
        if best:
            return best
        base = self.points[-1] if self.points else None
        if base is not None:
            for e in self.target():
                if e["type"] not in CURVES:
                    continue
                if "perp" in self.snaps:
                    p = geo.perpendicular_foot(e, base)
                    if p and math.hypot(p[0] - x, p[1] - y) < tol and math.dist(p, base) > 1e-6:
                        return p[0], p[1], "перпендикуляр", "perp"
                if "tangent" in self.snaps:
                    for p in geo.tangent_points(e, base):
                        if math.hypot(p[0] - x, p[1] - y) < tol:
                            return p[0], p[1], "касательная", "tangent"
        if self.iso:
            return self._iso_snap(x, y, base)
        if "grid" in self.snaps:
            s = min(self.grid_step(), 5.0)
            return round(x / s) * s, round(y / s) * s, "сетка", "grid"
        return x, y, "", ""

    def iso_step(self) -> float:
        return max(self.grid_step(), 5.0) if self.grid_step() < 50 else self.grid_step()

    def _iso_snap(self, x, y, base):
        """Изометрия: первая точка — в узел сетки; следующая — вдоль ближайшей оси 30°, 90° или 150° от предыдущей,
        длина — кратно шагу сетки (если привязка к сетке включена)."""
        s = self.iso_step()
        grid = "grid" in self.snaps
        if base is not None and self.tool in ("line", "axis"):
            dx, dy = x - base[0], y - base[1]
            ax, ay, name = min(ISO_AXES, key=lambda a: abs(dx * a[1] - dy * a[0]))
            t = dx * ax + dy * ay
            if grid:
                t = round(t / s) * s
            return base[0] + t * ax, base[1] + t * ay, f"изометрия {name}", "grid"
        if grid:
            i = round(x / (s * COS30))
            j = round((y - i * s * SIN30) / s)
            return i * s * COS30, i * s * SIN30 + j * s, "изометрическая сетка", "grid"
        return x, y, "", ""

    # ------------------------------------------------------------ фон и передний план
    def desk_color(self) -> QColor:
        paper = self.col["paper1"]
        return paper.darker(260) if paper.lightness() > 128 else paper.darker(180)

    def drawBackground(self, p: QPainter, rect: QRectF):
        sheet = self.sheet_bounds()
        p.save()
        p.resetTransform()
        vr = self.viewport().rect()
        if sheet is None:
            g = QLinearGradient(vr.topLeft(), vr.bottomRight())
            g.setColorAt(0, self.col["paper1"])
            g.setColorAt(1, self.col["paper2"])
            p.fillRect(vr, g)
        else:
            p.fillRect(vr, self.desk_color())   # тёмный «рабочий стол» вокруг листа
        p.restore()
        if sheet is not None:
            px = self.px()
            p.fillRect(sheet.translated(5 * px, -5 * px), QColor(0, 0, 0, 90))   # тень листа
            g = QLinearGradient(sheet.topLeft(), sheet.bottomRight())
            g.setColorAt(0, self.col["paper1"])
            g.setColorAt(1, self.col["paper2"])
            p.fillRect(sheet, g)
            for rects in (self.project.eskd.get("pages") or {}).values():   # листы спецификации и записки рядом с чертежом
                for x, y, pw, ph in rects:
                    p.fillRect(QRectF(x, y, pw, ph), self.col["paper1"])
            rect = rect.intersected(sheet)   # сетка строго в пределах листа
            if rect.isEmpty():
                return
        step = self.grid_step()
        major = step * (10 if step in (1.0, 10.0, 100.0) else 2)
        if self.iso:
            self._draw_iso_grid(p, rect)
        for s, color in (() if self.iso else ((step, self.col["grid_minor"]), (major, self.col["grid_major"]))):
            p.setPen(_pen(color, 1.0))
            x = math.floor(rect.left() / s) * s
            while x <= rect.right():
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                x += s
            y = math.floor(rect.top() / s) * s
            while y <= rect.bottom():
                p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                y += s
        p.setPen(_pen(self.col["axis_x"], 1.2))
        p.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
        p.setPen(_pen(self.col["axis_y"], 1.2))
        p.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))

    def _draw_iso_grid(self, p: QPainter, rect: QRectF):
        """Три семейства линий: вертикальные и под ±30° к горизонтали (оси изометрии на плоскости листа)."""
        s = self.iso_step()
        x0, x1 = min(rect.left(), rect.right()), max(rect.left(), rect.right())
        y0, y1 = min(rect.top(), rect.bottom()), max(rect.top(), rect.bottom())
        dx, t = s * COS30, SIN30 / COS30
        for k, color in ((1, self.col["grid_minor"]), (5, self.col["grid_major"])):
            p.setPen(_pen(color, 1.0))
            x = math.floor(x0 / (dx * k)) * dx * k
            while x <= x1:
                p.drawLine(QPointF(x, y0), QPointF(x, y1))
                x += dx * k
            for sign in (1, -1):      # y = ±x·tg30° + c, c кратно шагу
                lo = min(y0 - sign * t * x0, y0 - sign * t * x1)
                hi = max(y1 - sign * t * x0, y1 - sign * t * x1)
                c = math.floor(lo / (s * k)) * s * k
                while c <= hi:
                    p.drawLine(QPointF(x0, sign * t * x0 + c), QPointF(x1, sign * t * x1 + c))
                    c += s * k

    def _draw_live_dim(self, p: QPainter, a, b):
        """Размерная линия и дуга угла, которые идут за курсором при черчении отрезка."""
        L = math.dist(a, b)
        px = self.px()
        if L < 12 * px:
            return
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = -uy, ux
        off = 16 * px
        p.setPen(_pen(self.col["dim"], 1.0))
        a2, b2 = (a[0] + nx * off, a[1] + ny * off), (b[0] + nx * off, b[1] + ny * off)
        ext = off + 4 * px
        for q in (a, b):
            p.drawLine(QPointF(*q), QPointF(q[0] + nx * ext, q[1] + ny * ext))
        p.drawLine(QPointF(*a2), QPointF(*b2))
        ar = 7 * px
        for tip, d in ((a2, 1), (b2, -1)):      # стрелки
            for side in (1, -1):
                p.drawLine(QPointF(*tip), QPointF(tip[0] + d * ux * ar + side * nx * ar * 0.3, tip[1] + d * uy * ar + side * ny * ar * 0.3))
        ang = math.degrees(math.atan2(uy, ux)) % 360
        r = min(L * 0.5, 46 * px)
        if 0.5 < ang < 359.5:
            p.setPen(_pen(self.col["dim"], 1.0, [3, 3]))
            p.drawLine(QPointF(*a), QPointF(a[0] + r * 1.25, a[1]))
            p.setPen(_pen(self.col["dim"], 1.0))
            p.drawArc(QRectF(a[0] - r, a[1] - r, 2 * r, 2 * r), 0, int(-ang * 16))

    def drawForeground(self, p: QPainter, rect: QRectF):
        if self._box is not None:
            (x0, y0), (x1, y1) = self._box["start"], self._box["cur"]
            crossing = x1 < x0   # справа налево — секущая: зелёная, штриховая; слева направо — окно: синяя, сплошная
            c = QColor(36, 168, 92) if crossing else QColor(40, 110, 240)
            p.setPen(_pen(c, 1.3, [5, 3] if crossing else None))
            p.setBrush(QColor(c.red(), c.green(), c.blue(), 46))
            p.drawRect(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
            p.setBrush(Qt.NoBrush)
        grips = self.grips()
        if grips:   # характерные точки выделенного объекта — квадратные маркеры
            r = 3.5 * self.px()
            p.setPen(_pen(self.col["ink"], 1.0))
            p.setBrush(QBrush(self.col["select"]))
            for gx, gy, _ in grips:
                p.drawRect(QRectF(gx - r, gy - r, 2 * r, 2 * r))
            p.setBrush(Qt.NoBrush)
        if self.cursor is None:
            return
        cx, cy = self.cursor
        if self.tool == "block":
            from .preview import draw_entities

            ghost = self.block_ghost()
            if ghost:
                draw_entities(p, ghost, self.col["preview"], 1.6, 1.0)
            self._draw_marker(p, cx, cy)
            return
        p.setPen(_pen(self.col["preview"], 1.5, [4, 3]))
        p.setBrush(Qt.NoBrush)
        pts = self.points
        t = self.tool
        if pts:
            x0, y0 = pts[0]
            if t in ("line", "axis"):
                end = self._rubber_end()
                p.drawLine(QPointF(*pts[-1]), QPointF(*end))
                self._draw_live_dim(p, pts[-1], end)
                p.setPen(_pen(self.col["preview"], 1.5, [4, 3]))
            elif t == "leader" or (t in ("dim_h", "dim_v", "dim_a") and len(pts) == 1) or t == "mirror":
                p.drawLine(QPointF(*pts[-1]), QPointF(cx, cy))
            elif t == "rect":
                p.drawRect(QRectF(QPointF(x0, y0), QPointF(cx, cy)).normalized())
            elif t == "circle":
                r = math.hypot(cx - x0, cy - y0)
                p.drawEllipse(QPointF(x0, y0), r, r)
            elif t == "arc":
                r = math.hypot(pts[1][0] - x0, pts[1][1] - y0) if len(pts) > 1 else math.hypot(cx - x0, cy - y0)
                if len(pts) == 1:
                    p.drawEllipse(QPointF(x0, y0), r, r)
                else:
                    a0 = math.degrees(math.atan2(pts[1][1] - y0, pts[1][0] - x0))
                    a1 = math.degrees(math.atan2(cy - y0, cx - x0))
                    p.drawArc(QRectF(x0 - r, y0 - r, 2 * r, 2 * r), int(-a0 * 16), int(-((a1 - a0) % 360) * 16))
            elif t in ("dim_h", "dim_v", "dim_a") and len(pts) == 2:
                d = render(self._linear_dim(pts[0], pts[1], (cx, cy)))
                for sg in d.segs:
                    p.drawLine(QPointF(sg[0], sg[1]), QPointF(sg[2], sg[3]))
        self._draw_marker(p, cx, cy)

    def _draw_marker(self, p, cx, cy):
        r = 5 * self.px()
        p.setPen(_pen(self.col["select"], 1.6))
        p.setBrush(Qt.NoBrush)
        k = self.snap_kind
        if k == "end":
            p.drawRect(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        elif k == "mid":
            p.drawPolygon(QPolygonF([QPointF(cx - r, cy - r), QPointF(cx + r, cy - r), QPointF(cx, cy + r)]))
        elif k == "center":
            p.drawEllipse(QPointF(cx, cy), r, r)
        elif k == "intersection":
            p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            p.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))
        elif k == "perp":
            p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy - r))
            p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
        elif k == "tangent":
            p.drawEllipse(QPointF(cx, cy - r * 0.4), r * 0.6, r * 0.6)
            p.drawLine(QPointF(cx - r, cy + r * 0.2), QPointF(cx + r, cy + r * 0.2))
        else:
            p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
            p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))

    # ------------------------------------------------------------ инструменты
    def set_tool(self, tool: str):
        self.tool = tool
        self.hud.stop_edit()
        self.hud.hide_info()
        self.points, self.picked = [], []
        self.hint.emit(TOOLS[tool])
        self.setCursor(Qt.ArrowCursor if tool == "select" else Qt.CrossCursor)
        self.viewport().update()

    def cancel(self):
        self.hud.stop_edit()
        if self.points or self.picked:
            self.points, self.picked = [], []
        elif self.tool != "select":
            self.set_tool("select")
        elif self.selected:
            self.select([])
        self.viewport().update()

    def select(self, ids: list[str]):
        self.selected = ids
        self.rebuild()
        self.selectionChanged.emit(ids)

    def _scene_pos(self, ev) -> tuple[float, float]:
        sp = self.mapToScene(ev.position().toPoint())
        return sp.x(), sp.y()

    def group_of(self, eid: str) -> list[str]:
        """Что выделяет щелчок: элемент библиотеки или прямоугольник — целиком, остальное — по одному."""
        ids = library.group_ids(self.target(), eid)
        if len(ids) == 1:
            lines = params.rect_lines(self.target(), eid)
            if lines:
                ids = [e["id"] for e in lines]
        return ids

    # ------------------------------------------------------------ характерные точки
    def grip_target(self) -> list[dict] | None:
        """Объект с характерными точками: один выделенный отрезок, окружность, дуга или прямоугольник."""
        if self.tool != "select" or not self.selected:
            return None
        sel = set(self.selected)
        ents = [e for e in self.target() if e["id"] in sel]
        if len(ents) == 1 and ents[0]["type"] in CURVES:
            return ents
        if len(ents) == 4:
            lines = params.rect_lines(self.target(), ents[0]["id"])
            if lines and {e["id"] for e in lines} == sel:
                return lines
        return None

    def grips(self) -> list[tuple[float, float, str]]:
        ents = self.grip_target() if self._drag is None else self._drag["ents"]
        if not ents:
            return []
        if len(ents) == 4:
            x, y, w, h = params.rect_info(ents)
            return [(x, y, "c00"), (x + w, y, "c10"), (x + w, y + h, "c11"), (x, y + h, "c01")]
        e = ents[0]
        if e["type"] == "line":
            return [(e["x1"], e["y1"], "p1"), (e["x2"], e["y2"], "p2"), ((e["x1"] + e["x2"]) / 2, (e["y1"] + e["y2"]) / 2, "mid")]
        cx, cy, r = e["cx"], e["cy"], e["r"]
        if e["type"] == "circle":
            return [(cx, cy, "c")] + [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)), "q") for a in (0, 90, 180, 270)]
        mid = math.radians(e["a0"] + arc_sweep(e) / 2)
        return [(cx, cy, "c"), (*params.point_of(e, "s"), "s"), (*params.point_of(e, "e"), "e"),
                (cx + r * math.cos(mid), cy + r * math.sin(mid), "m")]

    def grip_at(self, x, y):
        tol = 6 * self.px()
        for gx, gy, role in self.grips():
            if abs(gx - x) <= tol and abs(gy - y) <= tol:
                return gx, gy, role
        return None

    def begin_drag(self, x, y, role):
        import copy

        ents = self.grip_target()
        ids = {e["id"] for e in ents}
        self.editStarted.emit()
        self._drag = {"role": role, "ents": ents, "orig": copy.deepcopy(ents), "start": (x, y), "moved": False}
        self._snap_cache = geo.snap_points([e for e in self.target() if e["type"] in CURVES and e["id"] not in ids])

    def drag_to(self, x, y):
        """Перетаскивание характерной точки: конец отрезка — длина и угол, середина — перенос; точка на ободе —
        радиус; угол прямоугольника — габарит от противоположного угла. Подсказка показывает размер на лету."""
        d = self._drag
        sx, sy, _, _ = self.snap(x, y)
        if not d["moved"] and math.hypot(x - d["start"][0], y - d["start"][1]) < 2 * self.px():
            return
        d["moved"] = True
        role, ents, orig = d["role"], d["ents"], d["orig"]
        dx, dy = sx - d["start"][0], sy - d["start"][1]
        if len(ents) == 4:
            x0, y0, w, h = params.rect_info(orig)
            opp = {"c00": (x0 + w, y0 + h), "c10": (x0, y0 + h), "c11": (x0, y0), "c01": (x0 + w, y0)}[role]
            if abs(sx - opp[0]) > params.EPS and abs(sy - opp[1]) > params.EPS:
                params.set_rect(ents, min(sx, opp[0]), min(sy, opp[1]), abs(sx - opp[0]), abs(sy - opp[1]))
            _, _, w, h = params.rect_info(ents)
            msg = f"Прямоугольник {w:.2f} × {h:.2f} мм"
        else:
            e, o = ents[0], orig[0]
            if e["type"] == "line":
                if role == "p1":
                    e["x1"], e["y1"] = sx, sy
                elif role == "p2":
                    e["x2"], e["y2"] = sx, sy
                else:
                    e.update(x1=o["x1"] + dx, y1=o["y1"] + dy, x2=o["x2"] + dx, y2=o["y2"] + dy)
                msg = f"L = {params.line_length(e):.2f} мм   α = {params.line_angle(e):.2f}°"
            else:
                if role == "c":
                    e["cx"], e["cy"] = o["cx"] + dx, o["cy"] + dy
                elif role in ("q", "m"):
                    e["r"] = max(math.hypot(sx - e["cx"], sy - e["cy"]), 1e-3)
                else:
                    e["a0" if role == "s" else "a1"] = math.degrees(math.atan2(sy - e["cy"], sx - e["cx"])) % 360
                msg = f"Ø {2 * e['r']:.2f}   R {e['r']:.2f} мм"
        params.sync_dims(self.project)
        self.rebuild()
        self.hint.emit(msg)
        if len(ents) == 4:
            self._hud_msg = f"Ш: {w:.2f} мм × В: {h:.2f} мм"
        elif ents[0]["type"] == "line":
            self._hud_msg = f"L: {params.line_length(ents[0]):.2f} мм | ∠: {params.line_angle(ents[0]) % 360:.1f}°"
        else:
            self._hud_msg = f"Ø: {2 * ents[0]['r']:.2f} мм (R: {ents[0]['r']:.2f} мм)"

    def end_drag(self):
        d, self._drag = self._drag, None
        if d is None:
            return
        if d["moved"]:
            self.rebuild()
            self.edited.emit()
        else:
            self.editFailed.emit()
            self.rebuild()

    # ------------------------------------------------------------ рамка и перенос группы
    def select_all(self):
        """Ctrl+A: всё начерченное на полотне (рамка и штамп — не объекты, их не трогает)."""
        self.select([e["id"] for e in self.target()])

    def finish_box(self, mode=None):
        """Рамка выделения. mode: None — заменить выделение; "add" (Shift) — добавить попавшие к выделенным;
        "toggle" (Ctrl) — инвертировать попавшие: выделенные снять, невыделенные добавить."""
        mode = "add" if mode is True else (mode or None)
        b, self._box = self._box, None
        (x0, y0), (x1, y1) = b["start"], b["cur"]
        if max(abs(x1 - x0), abs(y1 - y0)) < 3 * self.px():   # щелчок по пустому месту
            if not mode:
                self.select([])
            else:
                self.viewport().update()
            return
        ids = selection.box_select(self.target(), (x0, y0, x1, y1), crossing=x1 < x0)
        hit = len(ids)
        if mode == "add":
            ids = self.selected + [i for i in ids if i not in self.selected]
        elif mode == "toggle":
            inside = set(ids)
            ids = [i for i in self.selected if i not in inside] + [i for i in ids if i not in self.selected]
        self.select(ids)
        kind = "секущей рамкой — и пересечённые" if x1 < x0 else "рамкой — только целиком внутри"
        how = {"add": " (Shift — добавлено)", "toggle": " (Ctrl — выделение попавших инвертировано)"}.get(mode, "")
        self.hint.emit(f"Попало в рамку {hit}, {kind}{how}; выбрано: {len(ids)}")

    def begin_move(self, x, y):
        import copy

        sel = set(self.selected)
        ents = [e for e in self.target() if e["id"] in sel]
        sx, sy, _, _ = self.snap(x, y)      # за точку объекта: её и прикладываем к точкам других
        self.editStarted.emit()
        self._move = {"ents": ents, "orig": copy.deepcopy(ents), "start": (sx, sy), "raw": (x, y), "moved": False}
        self._snap_cache = geo.snap_points([e for e in self.target() if e["type"] in CURVES and e["id"] not in sel])

    def move_to(self, x, y):
        m = self._move
        if not m["moved"] and math.hypot(x - m["raw"][0], y - m["raw"][1]) < 3 * self.px():
            return
        m["moved"] = True
        sx, sy, _, _ = self.snap(x, y)
        dx, dy = sx - m["start"][0], sy - m["start"][1]
        for e, o in zip(m["ents"], m["orig"]):
            e.update(copy_of(o))
        selection.move(m["ents"], dx, dy)
        params.sync_dims(self.project)
        self.rebuild()
        self.hint.emit(f"Перенос: ΔX {dx:.2f}  ΔY {dy:.2f} мм ({len(m['ents'])} шт.)")
        self._hud_msg = f"ΔX: {dx:.2f} мм | ΔY: {dy:.2f} мм"

    def end_move(self):
        m, self._move = self._move, None
        if m["moved"]:
            self.rebuild()
            self.edited.emit()
            return
        self.editFailed.emit()
        if m.get("only") is not None:   # щелчок по одному из выбранных без переноса — выбрать только его
            self.select(m["only"])
        else:
            self.rebuild()

    def right_click(self, x, y, global_pos: QPoint):
        """ПКМ как в КОМПАС: во время черчения — завершить команду; по объекту — выделить его и открыть редактор;
        при выделенной группе — редактор группы, выделение не сбрасывается."""
        if self.tool != "select":
            self.points, self.picked = [], []
            self.set_tool("select")
            self.toolEnded.emit()
            return
        best = self.pick(x, y)
        if best is not None and best not in self.selected:
            self.select(self.group_of(best))
        if self.selected:
            self.contextRequested.emit(global_pos)

    def pick(self, x, y, kinds=None) -> str | None:
        tol = 8 * self.px()
        best, bd = None, tol
        for e in self.target():
            if kinds and e["type"] not in kinds:
                continue
            d = geo.distance_to(e, x, y) if e["type"] in CURVES else pick_distance(e, x, y)
            if d < bd:
                best, bd = e["id"], d
        return best

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self._pan = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if ev.button() == Qt.RightButton:
            self.right_click(*self._scene_pos(ev), ev.globalPosition().toPoint())
            return
        if ev.button() != Qt.LeftButton:
            return
        x, y = self._scene_pos(ev)
        if self.tool == "select":
            add = bool(ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier))   # Shift или Ctrl — добавить/снять
            grip = self.grip_at(x, y)
            if grip and not add:
                self.begin_drag(grip[0], grip[1], grip[2])
                return
            best = self.pick(x, y)
            if best is None:   # пустое место: рамка (без движения — снять выделение)
                mode = "toggle" if ev.modifiers() & Qt.ControlModifier else "add" if add else None
                self._box = {"start": (x, y), "cur": (x, y), "add": add, "mode": mode}
                return
            group = self.group_of(best)   # элемент библиотеки, прямоугольник — целиком
            if add:
                self.select([i for i in self.selected if i not in group] if best in self.selected else self.selected + group)
                return
            only = None
            if best not in self.selected:
                self.select(group)
            elif len(self.selected) > len(group):
                only = group
            self.begin_move(x, y)   # зажатая ЛКМ на выбранном — перенос всей группы
            self._move["only"] = only
            return
        self.click(x, y)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.LeftButton or self.tool != "select":
            return super().mouseDoubleClickEvent(ev)
        x, y = self._scene_pos(ev)
        eid = self.pick(x, y)
        if eid:
            self.editEntity.emit(eid)
        elif self.sheet_bounds() is not None:
            cell = hit_cell(self.project.frame, x, y)
            if cell is not None:
                self.stampField.emit(cell.field or "name")

    def mouseMoveEvent(self, ev):
        self._mouse = ev.position()
        self._move_event(ev)
        self._hud_update()

    def _move_event(self, ev):
        if self._pan is not None:
            d = ev.position() - self._pan
            self._pan = ev.position()
            self.scroll_by(d.x(), d.y())
            return
        x, y = self._scene_pos(ev)
        if self._drag is not None or self._move is not None:
            self.cursor = (x, y)
            (self.drag_to if self._drag is not None else self.move_to)(x, y)
            self.cursorMoved.emit(x, y, "")
            return
        if self._box is not None:
            self._box["cur"] = (x, y)
            self.cursor = (x, y)
            self.cursorMoved.emit(x, y, "")
            self.viewport().update()
            return
        if self.tool in ("select", "trim", "extend", "chamfer", "fillet", "dim_dia", "dim_rad", "hatch") or (self.tool == "offset" and not self.picked):
            self.cursor, self.snap_label, self.snap_kind = (x, y), "", ""
        else:
            sx, sy, label, kind = self.snap(x, y)
            self.cursor, self.snap_label, self.snap_kind = (sx, sy), label, kind
        self.cursorMoved.emit(self.cursor[0], self.cursor[1], self.snap_label)
        self._emit_live()
        self.viewport().update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._drag is not None:
            self.end_drag()
            self._hud_msg = ""
            self._hud_update()
            return
        if ev.button() == Qt.LeftButton and self._move is not None:
            self.end_move()
            self._hud_msg = ""
            self._hud_update()
            return
        if ev.button() == Qt.LeftButton and self._box is not None:
            self._box["cur"] = self._scene_pos(ev)
            self.finish_box(self._box.get("mode"))
            return
        if ev.button() == Qt.MiddleButton:
            self._pan = None
            self.setCursor(Qt.ArrowCursor if self.tool == "select" else Qt.CrossCursor)

    def leaveEvent(self, ev):
        if self.hud.editing:      # курсор ушёл в поле ввода у перекрестия — черчение не прерывается
            return
        self.cursor = None
        self.hud.hide_info()
        self.viewport().update()

    # ------------------------------------------------------------ динамический ввод у курсора
    def _hud_stage(self):
        """Что сейчас показывать и вводить: (текст бейджа, поля ввода, значения от курсора). Поле: (ключ, подпись, значение, единица)."""
        if self.cursor is None:
            return "", [], {}
        cx, cy = self.cursor
        t, pts = self.tool, self.points
        if self._drag is not None or self._move is not None:
            return self._hud_msg, [], {}
        if t == "select":
            eid = self.pick(cx, cy) if self._box is None else None
            e = self.project.find(eid) if eid else None
            at = f"(X: {cx:.2f}, Y: {cy:.2f})"
            if e is None or e["type"] not in CURVES:
                return "", [], {}
            if e["type"] == "line":
                return f"L: {params.line_length(e):.2f} мм | ∠: {params.line_angle(e) % 360:.1f}° | {at}", [], {}
            if e["type"] == "circle":
                return f"Ø: {2 * e['r']:.2f} мм (R: {e['r']:.2f} мм) | {at}", [], {}
            return f"R: {e['r']:.2f} мм | ∠: {arc_sweep(e):.1f}° | {at}", [], {}
        if t not in DRAW_TOOLS:
            return "", [], {}
        if not pts:
            v = {"x": cx, "y": cy}
            return f"X: {cx:.2f} | Y: {cy:.2f}", [("x", "X", cx, "мм"), ("y", "Y", cy, "мм")], v
        x0, y0 = pts[-1] if t in ("line", "axis") else pts[0]
        L = math.hypot(cx - x0, cy - y0)
        ang = math.degrees(math.atan2(cy - y0, cx - x0)) % 360
        if t in ("line", "axis"):
            return (f"L: {L:.2f} мм | ∠: {ang:.1f}°", [("length", "L", L, "мм"), ("angle", "∠", ang, "°")], {"length": L, "angle": ang})
        if t == "rect":
            w, h = abs(cx - x0), abs(cy - y0)
            return f"Ш: {w:.2f} мм × В: {h:.2f} мм", [("w", "Ш", w, "мм"), ("h", "В", h, "мм")], {"w": w, "h": h}
        if t == "circle" or (t == "arc" and len(pts) == 1):
            f = [("d", "Ø", 2 * L, "мм"), ("r", "R", L, "мм")]
            return f"Ø: {2 * L:.2f} мм (R: {L:.2f} мм)", f if t == "circle" else f[::-1], {"d": 2 * L, "r": L}
        r = math.hypot(pts[1][0] - x0, pts[1][1] - y0)     # дуга: центр и начало заданы — угол раствора
        sweep = (ang - math.degrees(math.atan2(pts[1][1] - y0, pts[1][0] - x0))) % 360
        return f"R: {r:.2f} мм | ∠: {sweep:.1f}°", [("angle", "∠", sweep, "°")], {"angle": sweep}

    def hud_text(self) -> str:
        return self._hud_stage()[0]

    def _hud_update(self):
        pos = self._mouse
        if pos is None and self.cursor is not None:
            pos = QPointF(self.mapFromScene(QPointF(*self.cursor)))
        if pos is None:
            return
        text, _, values = self._hud_stage()
        if self.hud.editing:
            self.hud.follow(values)
        self.hud.show_info(text, pos)

    def _rubber_end(self) -> tuple[float, float]:
        """Конец резиновой линии: курсор, а если длину или угол уже ввели с клавиатуры — по введённому."""
        if self.hud.editing and self.points and self.tool in ("line", "axis"):
            v = self.hud.values()
            if v and {"length", "angle"} <= set(v):
                a = math.radians(v["angle"])
                return self.points[-1][0] + v["length"] * math.cos(a), self.points[-1][1] + v["length"] * math.sin(a)
        return self.cursor

    def start_typing(self, text: str = "") -> bool:
        """Начать ввод размеров у курсора (первая цифра уже нажата). False — вводить сейчас нечего."""
        if self.cursor is None and self.points:
            self.cursor = self.points[-1]
        _, fields, _ = self._hud_stage()
        if not fields:
            return False
        self._hud_update()
        self.hud.start_edit(fields, text)
        self.viewport().update()
        return True

    def _hud_commit(self, v: dict):
        """Enter в полях у курсора: размер фиксируется так же, как щелчком или из панели «Параметры»."""
        locked = v.pop("_locked", set())
        t, pts = self.tool, self.points
        cx, cy = self.cursor if self.cursor is not None else (0.0, 0.0)
        try:
            if not pts:
                self.points.append((v["x"], v["y"]))
            elif t in ("line", "axis"):
                self.apply_input({"length": v["length"], "angle": v["angle"]})
            elif t == "rect":
                x0, y0 = pts[0]
                x1 = x0 + math.copysign(v["w"], cx - x0 if v["w"] > 0 and cx != x0 else v["w"])
                y1 = y0 + math.copysign(v["h"], cy - y0 if v["h"] > 0 and cy != y0 else v["h"])
                if self.apply_input({"x": min(x0, x1), "y": min(y0, y1), "w": abs(x1 - x0), "h": abs(y1 - y0)}):
                    self.points = []
            elif t == "circle":
                r = v["r"] if "r" in locked and "d" not in locked else v["d"] / 2
                if self.apply_input({"cx": pts[0][0], "cy": pts[0][1], "r": r}):
                    self.points = []
            elif t == "arc" and len(pts) == 1:
                r = v["r"] if "r" in locked or "d" not in locked else v["d"] / 2
                a = math.atan2(cy - pts[0][1], cx - pts[0][0])
                self.points.append((pts[0][0] + r * math.cos(a), pts[0][1] + r * math.sin(a)))
            elif t == "arc":
                (x0, y0), (sx, sy) = pts[0], pts[1]
                a0 = math.degrees(math.atan2(sy - y0, sx - x0))
                if self.apply_input({"cx": x0, "cy": y0, "r": math.hypot(sx - x0, sy - y0), "a0": a0, "a1": a0 + v["angle"]}):
                    self.points = []
        except (KeyError, ValueError) as exc:
            self.hint.emit(f"⚠ {exc}")
        self.setFocus()
        self._hud_update()
        self.viewport().update()

    def _emit_live(self):
        if self.cursor is None or self.tool not in DRAW_TOOLS:
            return
        cx, cy = self.cursor
        if not self.points:
            self.live.emit({"x1": cx, "y1": cy, "cx": cx, "cy": cy, "x": cx, "y": cy, "x2": cx, "y2": cy})
            return
        x0, y0 = self.points[0]
        L = math.hypot(cx - x0, cy - y0)
        ang = math.degrees(math.atan2(cy - y0, cx - x0)) % 360
        self.live.emit({"x1": self.points[-1][0], "y1": self.points[-1][1], "length": math.hypot(cx - self.points[-1][0], cy - self.points[-1][1]),
                        "angle": math.degrees(math.atan2(cy - self.points[-1][1], cx - self.points[-1][0])) % 360,
                        "x": min(x0, cx), "y": min(y0, cy), "w": abs(cx - x0), "h": abs(cy - y0), "cx": x0, "cy": y0, "r": L, "a1": ang,
                        "x2": cx, "y2": cy})

    # ------------------------------------------------------------ фиксация
    def _commit(self, fn):
        """Правка через fn() со снимком для отмены; ValueError — подсказка, без изменений."""
        self.editStarted.emit()
        try:
            fn()
        except ValueError as exc:
            self.hint.emit(f"⚠ {exc}")
            self.editFailed.emit()
            return False
        params.sync_dims(self.project)   # ассоциативные размеры — за геометрией
        self.rebuild()
        self.edited.emit()
        return True

    def _circle(self, cx, cy, r) -> dict:
        """Окружность текущим стилем; галочка «Осевые линии» в панели — с центровыми линиями."""
        c = make_circle(cx, cy, r, self.style)
        if self.params["circle_axes"]:
            c["axes"] = True
        return c

    def _add(self, entities):
        self._commit(lambda: self.target().extend(entities))

    @staticmethod
    def _linear_dim_kind(tool):
        return {"dim_h": "horizontal", "dim_v": "vertical", "dim_a": "aligned"}[tool]

    def _linear_dim(self, a, b, c) -> dict:
        kind = self._linear_dim_kind(self.tool)
        if kind == "horizontal":
            off = c[1] - a[1]
        elif kind == "vertical":
            off = c[0] - a[0]
        else:
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            off = (c[0] - a[0]) * -(b[1] - a[1]) / L + (c[1] - a[1]) * (b[0] - a[0]) / L
        return make_dim(a[0], a[1], b[0], b[1], off, kind)

    # ------------------------------------------------------------ вставка элемента библиотеки
    def start_block(self, block_id: str, label: str | None = None):
        b = library.get_block(block_id)
        if block_id != self.params["blk_id"]:    # другой элемент — с нулевым поворотом и в своём масштабе
            self.params.update(blk_rot=0.0, blk_scale=1.0)
        self.params.update(blk_id=block_id, blk_label=b.label if label is None else label)
        self.set_tool("block")
        self.hint.emit(f"«{b.name}»: " + TOOLS["block"])

    def _block_live(self):
        pr = self.params
        self.live.emit({"blk_rot": pr["blk_rot"], "blk_scale": pr["blk_scale"], "blk_label": pr["blk_label"]})
        self.viewport().update()

    def rotate_block(self, deg: float = 90.0):
        self.params["blk_rot"] = (self.params["blk_rot"] + deg) % 360
        self._block_live()

    def scale_block(self, k: float):
        self.params["blk_scale"] = min(100.0, max(0.05, round(self.params["blk_scale"] * k, 4)))
        self._block_live()

    def block_ghost(self) -> list[dict]:
        """Элемент там, где он встанет по щелчку: в точке курсора с привязкой, с поворотом и масштабом."""
        pr = self.params
        if not pr["blk_id"] or self.cursor is None:
            return []
        try:
            return library.instantiate(pr["blk_id"], *self.cursor, pr["blk_rot"], pr["blk_scale"], pr["blk_label"])
        except ValueError:
            return []

    def keyPressEvent(self, ev):
        if self.tool == "block" and ev.key() in (Qt.Key_Space, Qt.Key_R) and not ev.modifiers() & Qt.ControlModifier:
            self.rotate_block(90)
            return
        ch = ev.text()
        if self.hud.editing:       # ввод уже идёт, а клавиша пришла холсту — она для поля у курсора
            from PySide6.QtWidgets import QApplication

            field = next((f for f in self.hud.fields.values() if f.hasFocus()), next(iter(self.hud.fields.values())))
            field.setFocus()
            QApplication.sendEvent(field, ev)
            return
        if self.tool in DRAW_TOOLS and ch and (ch.isdigit() or ch in "-.,") and not ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            if self.start_typing("-" if ch == "-" else ch.replace(",", ".")):     # цифра — сразу в поле у курсора
                return
        if self.tool in DRAW_TOOLS and ev.key() == Qt.Key_Tab and self.start_typing():
            return
        super().keyPressEvent(ev)

    def click(self, x, y):
        """Щелчок инструментом (из мыши или из тестов). Точка привязывается так же, как при движении мыши."""
        t = self.tool
        self.hud.stop_edit(silent=True)
        if t == "block":
            sx, sy, _, _ = self.snap(x, y)
            pr = self.params
            if self._commit(lambda: self.target().extend(library.instantiate(pr["blk_id"], sx, sy, pr["blk_rot"], pr["blk_scale"], pr["blk_label"]))):
                pr["blk_label"] = library.next_label(pr["blk_label"])   # QF1 → QF2: следующий такой же — сразу со своим номером
                self._block_live()
            return
        if t in ("trim", "extend", "chamfer", "fillet", "dim_dia", "dim_rad", "dim_ang", "offset", "hatch", "pattern_circ", "mirror"):
            return self._object_click(x, y)
        sx, sy, _, _ = self.snap(x, y)
        self.points.append((sx, sy))
        pts = self.points
        try:
            if t in ("line", "axis") and len(pts) == 2:
                if math.dist(*pts) > 1e-9:
                    self._add([make_line(*pts[0], *pts[1], self.style if t == "line" else "axis")])
                self.points = [pts[1]] if t == "line" and not self._closes_chain(pts[1]) else []
            elif t == "rect" and len(pts) == 2:
                (x0, y0), (x1, y1) = pts
                if abs(x1 - x0) > 1e-9 and abs(y1 - y0) > 1e-9:
                    self._add(make_rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0), self.style))
                self.points = []
            elif t == "circle" and len(pts) == 2:
                r = math.dist(*pts)
                if r > 1e-9:
                    self._add([self._circle(*pts[0], r)])
                self.points = []
            elif t == "arc" and len(pts) == 3:
                (cx, cy), (sx_, sy_), (ex, ey) = pts
                r = math.hypot(sx_ - cx, sy_ - cy)
                if r > 1e-9:
                    self._add([make_arc(cx, cy, r, math.degrees(math.atan2(sy_ - cy, sx_ - cx)), math.degrees(math.atan2(ey - cy, ex - cx)), self.style)])
                self.points = []
            elif t in ("dim_h", "dim_v", "dim_a") and len(pts) == 3:
                if math.dist(pts[0], pts[1]) > 1e-9:   # концы на точках объектов — размер ассоциативный (управляющий)
                    self._add([params.attach_dim(self.project, self._linear_dim(*pts))])
                self.points = []
            elif t == "leader" and len(pts) == 2:
                self._add([make_leader(*pts[0], *pts[1], self.params["leader_text"])])
                self.points = []
            elif t == "rough" and len(pts) == 1:
                self._add([make_rough(*pts[0], self.params["rough_value"], self.params["rough_param"])])
                self.points = []
            elif t == "frame" and len(pts) == 1:
                from .ops import set_frame

                fr = self.project.frame or {}
                self._commit(lambda: set_frame(self.project, fr.get("format", "A3"), fr.get("orient", "landscape"), *pts[0]))
                self.points = []
                self.set_tool("select")
        except ValueError as exc:
            self.hint.emit(f"⚠ {exc}")
            self.points = []
        self.viewport().update()

    def _object_click(self, x, y):
        t = self.tool
        ents = self.target()
        p = (x, y)
        if t == "trim":
            eid = self.pick(x, y, CURVES)
            if eid:
                self._commit(lambda: edit2d.trim(ents, eid, p))
        elif t == "extend":
            eid = self.pick(x, y, ("line", "arc"))
            if eid:
                self._commit(lambda: edit2d.extend(ents, eid, p))
        elif t in ("chamfer", "fillet", "dim_ang"):
            eid = self.pick(x, y, ("line",))
            if eid and len(self.picked) < 2:
                self.picked.append((eid, p))
                self.hint.emit("Второй отрезок" if len(self.picked) == 1 else "Положение дуги размера")
            elif len(self.picked) == 2 and t == "dim_ang":
                self._commit(lambda: ents.append(self._angle_dim(p)))
                self.picked = []
                return
            if len(self.picked) == 2 and t != "dim_ang":
                (i1, p1), (i2, p2) = self.picked
                pr = self.params
                if t == "chamfer":
                    ang = pr["chamfer_angle"] or None
                    self._commit(lambda: edit2d.chamfer(ents, i1, p1, i2, p2, pr["chamfer_d1"], None if ang else pr["chamfer_d2"], ang))
                else:
                    self._commit(lambda: edit2d.fillet(ents, i1, p1, i2, p2, pr["fillet_r"]))
                self.picked = []
        elif t in ("dim_dia", "dim_rad"):
            if not self.picked:
                eid = self.pick(x, y, ("circle", "arc"))
                if eid:
                    self.picked.append((eid, p))
                    self.hint.emit("Укажите направление размерной линии")
            else:
                c = self.project.find(self.picked[0][0])
                ang = math.degrees(math.atan2(y - c["cy"], x - c["cx"]))
                mk = make_diadim if t == "dim_dia" else make_raddim
                self.picked = []
                self._add([{**mk(c["cx"], c["cy"], c["r"], ang), "ref": c["id"]}])
        elif t == "offset":
            if not self.picked:
                eid = self.pick(x, y, CURVES)
                if eid:
                    self.picked.append((eid, p))
                    self.hint.emit("Укажите сторону смещения")
            else:
                eid = self.picked[0][0]
                pr = self.params
                self.picked = []
                self._commit(lambda: edit2d.offset(ents, eid, pr["offset_d"], p, pr["offset_whole"], self.style))
        elif t == "hatch":
            pr = self.params
            self._commit(lambda: ents.append(make_hatch(edit2d.hatch_region(ents, p), pr["hatch_pattern"], pr["hatch_step"], pr["hatch_angle"])))
        elif t == "pattern_circ":
            pr = self.params
            sx, sy, _, _ = self.snap(x, y)
            self._commit(lambda: edit2d.pattern_circular(ents, self.selected, (sx, sy), int(pr["pat_count"]), pr["pat_angle"]))
        elif t == "mirror":
            sx, sy, _, _ = self.snap(x, y)
            self.points.append((sx, sy))
            if len(self.points) == 2:
                a, b = self.points
                self.points = []
                self._commit(lambda: edit2d.mirror(ents, self.selected, a, b, self.params["mirror_keep"]))
        self.viewport().update()

    def _angle_dim(self, p):
        (i1, p1), (i2, p2) = self.picked
        l1, l2 = self.project.find(i1), self.project.find(i2)
        hits = geo.intersect({**l1, "x1": l1["x1"] - (l1["x2"] - l1["x1"]) * 1e3, "y1": l1["y1"] - (l1["y2"] - l1["y1"]) * 1e3,
                              "x2": l1["x2"] + (l1["x2"] - l1["x1"]) * 1e3, "y2": l1["y2"] + (l1["y2"] - l1["y1"]) * 1e3},
                             {**l2, "x1": l2["x1"] - (l2["x2"] - l2["x1"]) * 1e3, "y1": l2["y1"] - (l2["y2"] - l2["y1"]) * 1e3,
                              "x2": l2["x2"] + (l2["x2"] - l2["x1"]) * 1e3, "y2": l2["y2"] + (l2["y2"] - l2["y1"]) * 1e3})
        if not hits:
            raise ValueError("отрезки параллельны — угла нет")
        c = hits[0]
        a1 = math.degrees(math.atan2(p1[1] - c[1], p1[0] - c[0]))
        a2 = math.degrees(math.atan2(p2[1] - c[1], p2[0] - c[0]))
        if (a2 - a1) % 360 > 180:
            a1, a2 = a2, a1
        return make_angdim(c[0], c[1], a1, a2, max(math.dist(p, c), 5.0))

    def apply_now(self):
        """Применить инструмент без щелчка (массив по сетке)."""
        if self.tool == "pattern_lin":
            pr = self.params
            return self._commit(lambda: edit2d.pattern_linear(self.target(), self.selected, int(pr["pat_nx"]), int(pr["pat_ny"]), pr["pat_dx"], pr["pat_dy"]))
        return False

    def apply_input(self, v: dict) -> bool:
        """Точный ввод из панели: создаёт объект по числам. Для отрезка — по началу, длине и углу."""
        t = self.tool
        try:
            if t in ("line", "axis"):
                x1, y1 = (self.points[-1] if self.points else (v["x1"], v["y1"]))
                if v.get("use_end"):
                    x2, y2 = v["x2"], v["y2"]
                else:
                    a = math.radians(v["angle"])
                    x2, y2 = x1 + v["length"] * math.cos(a), y1 + v["length"] * math.sin(a)
                if math.hypot(x2 - x1, y2 - y1) < 1e-9:
                    raise ValueError("длина отрезка равна нулю")
                ok = self._commit(lambda: self.target().append(make_line(x1, y1, x2, y2, self.style if t == "line" else "axis")))
                self.points = [(x2, y2)] if ok and t == "line" else []
                return ok
            if t == "rect":
                return self._commit(lambda: self.target().extend(make_rect(v["x"], v["y"], v["w"], v["h"], self.style)))
            if t == "circle":
                r = v["d"] / 2 if v.get("by_d") else v["r"]
                return self._commit(lambda: self.target().append(self._circle(v["cx"], v["cy"], r)))
            if t == "arc":
                return self._commit(lambda: self.target().append(make_arc(v["cx"], v["cy"], v["r"], v["a0"], v["a1"], self.style)))
        except (KeyError, ValueError) as exc:
            self.hint.emit(f"⚠ {exc}")
        finally:
            self.viewport().update()
        return False

    def _closes_chain(self, p) -> bool:
        """Цепочка отрезков закрылась, если точка совпала с концом другого отрезка, кроме последнего."""
        ents = self.target()
        if len(ents) < 2:
            return False
        last = ents[-1]["id"]
        for e in ents:
            if e["type"] == "line" and e["id"] != last:
                if math.dist(p, (e["x1"], e["y1"])) < 1e-6 or math.dist(p, (e["x2"], e["y2"])) < 1e-6:
                    return True
        return False
