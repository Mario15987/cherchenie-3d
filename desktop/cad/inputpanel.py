"""Панель параметров инструмента: точный ввод с клавиатуры (длина, угол, координаты, радиус…) и настройки
инструментов редактирования. Пока поле не в фокусе, в нём живое значение от мыши; Enter — создать."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .model import HATCH_PATTERNS, STYLE_LABEL, STYLES

TITLES = {
    "line": "Отрезок", "axis": "Осевая линия", "rect": "Прямоугольник", "circle": "Окружность", "arc": "Дуга",
    "chamfer": "Фаска", "fillet": "Скругление", "offset": "Эквидистанта", "hatch": "Штриховка", "leader": "Выноска",
    "rough": "Шероховатость", "mirror": "Симметрия", "pattern_lin": "Массив по сетке", "pattern_circ": "Массив по окружности",
    "trim": "Усечь кривую", "extend": "Удлинить", "dim_h": "Размер горизонтальный", "dim_v": "Размер вертикальный",
    "dim_a": "Размер параллельный", "dim_dia": "Размер диаметральный", "dim_rad": "Размер радиальный",
    "dim_ang": "Размер угловой", "frame": "Рамка", "block": "Вставка элемента",
}

# поле -> (подпись, мин, макс)
FIELDS = {
    "line": [("length", "Длина L", 0, 1e5), ("angle", "Угол α, °", -360, 360), ("x1", "Начало X1", -1e5, 1e5), ("y1", "Начало Y1", -1e5, 1e5),
             ("x2", "Конец X2", -1e5, 1e5), ("y2", "Конец Y2", -1e5, 1e5)],
    "axis": [("length", "Длина L", 0, 1e5), ("angle", "Угол α, °", -360, 360), ("x1", "Начало X1", -1e5, 1e5), ("y1", "Начало Y1", -1e5, 1e5),
             ("x2", "Конец X2", -1e5, 1e5), ("y2", "Конец Y2", -1e5, 1e5)],
    "rect": [("x", "X угла", -1e5, 1e5), ("y", "Y угла", -1e5, 1e5), ("w", "Ширина", -1e5, 1e5), ("h", "Высота", -1e5, 1e5)],
    "circle": [("d", "Диаметр Ø", 0, 2e5), ("r", "Радиус R", 0, 1e5), ("cx", "Центр X", -1e5, 1e5), ("cy", "Центр Y", -1e5, 1e5)],
    "arc": [("r", "Радиус R", 0, 1e5), ("d", "Диаметр Ø", 0, 2e5), ("cx", "Центр X", -1e5, 1e5), ("cy", "Центр Y", -1e5, 1e5),
            ("a0", "Угол начала, °", -360, 360), ("a1", "Угол конца, °", -360, 360)],
}
PARAMS = {
    "chamfer": [("chamfer_d1", "Катет 1", 0.01, 1e4), ("chamfer_d2", "Катет 2", 0.01, 1e4), ("chamfer_angle", "или угол, ° (0 — по катетам)", 0, 179)],
    "fillet": [("fillet_r", "Радиус", 0.01, 1e4)],
    "offset": [("offset_d", "Расстояние", 0.01, 1e4)],
    "hatch": [("hatch_step", "Шаг", 0.2, 100), ("hatch_angle", "Угол, °", -180, 180)],
    "pattern_lin": [("pat_dx", "Шаг по X", -1e4, 1e4), ("pat_dy", "Шаг по Y", -1e4, 1e4)],
    "pattern_circ": [("pat_angle", "Угол заполнения, °", 1, 360)],
}
INT_PARAMS = {"pattern_lin": [("pat_nx", "Копий по X", 1, 500), ("pat_ny", "Копий по Y", 1, 500)],
              "pattern_circ": [("pat_count", "Количество", 2, 500)]}


class ToolPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = None
        self.tool = "select"
        self.spins: dict[str, QDoubleSpinBox] = {}
        self.edits: dict[str, QLineEdit] = {}
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.title)
        box = QWidget()
        box.setLayout(self.form)
        v.addWidget(box)
        v.addStretch(1)

    def bind(self, view, tool: str):
        if self.view is not None:
            try:
                self.view.live.disconnect(self._live)
            except (RuntimeError, TypeError):
                pass
        self.view, self.tool = view, tool
        view.live.connect(self._live)
        self._build()

    def _clear(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.spins, self.edits = {}, {}

    def _spin(self, value, lo, hi, on_change=None, decimals=2):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setValue(value)
        s.setKeyboardTracking(True)
        s.lineEdit().returnPressed.connect(self.apply)
        if on_change:
            s.valueChanged.connect(on_change)
        return s

    def _build(self):
        self._clear()
        t, v = self.tool, self.view
        self.title.setText(f"ПАРАМЕТРЫ · {TITLES.get(t, 'ВЫБОР').upper()}")
        if t in ("line", "rect", "circle", "arc"):
            st = QComboBox()
            for k in STYLES:
                st.addItem(STYLE_LABEL[k], k)
            st.setCurrentIndex(STYLES.index(v.style))
            st.currentIndexChanged.connect(lambda i: setattr(v, "style", STYLES[i]))
            self.form.addRow("Тип линии", st)
        if t in FIELDS:
            for key, label, lo, hi in FIELDS[t]:
                self.spins[key] = self._spin(0.0, lo, hi)
                self.form.addRow(label, self.spins[key])
            if t in ("circle", "arc"):   # Ø и R связаны жёстко
                self.spins["r"].valueChanged.connect(lambda x: self._sync("d", 2 * x))
                self.spins["d"].valueChanged.connect(lambda x: self._sync("r", x / 2))
            if t in ("line", "axis"):
                # L, α и начало задают конец; конец задаёт L и α — как в КОМПАС
                for k in ("length", "angle", "x1", "y1"):
                    self.spins[k].valueChanged.connect(self._line_end_from_polar)
                for k in ("x2", "y2"):
                    self.spins[k].valueChanged.connect(self._line_polar_from_end)
                self.spins["length"].setValue(20)
            if t == "circle":
                ax = QCheckBox("Осевые линии")
                ax.setChecked(bool(v.params.get("circle_axes")))
                ax.toggled.connect(lambda on: v.params.__setitem__("circle_axes", on))
                self.form.addRow("", ax)
            ok = QPushButton("Создать (Enter)")
            ok.setObjectName("primary")
            ok.clicked.connect(self.apply)
            self.form.addRow(ok)
            hint = QLabel("Пока поле не в фокусе, в нём значение от мыши. Начните вводить — и нажмите Enter.")
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            self.form.addRow(hint)
        for key, label, lo, hi in PARAMS.get(t, []):
            self.form.addRow(label, self._spin(float(v.params[key]), lo, hi, lambda x, k=key: v.params.__setitem__(k, x)))
        for key, label, lo, hi in INT_PARAMS.get(t, []):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(v.params[key]))
            s.valueChanged.connect(lambda x, k=key: v.params.__setitem__(k, x))
            self.form.addRow(label, s)
        if t == "hatch":
            c = QComboBox()
            for k, lab in HATCH_PATTERNS.items():
                c.addItem(lab, k)
            c.setCurrentIndex(list(HATCH_PATTERNS).index(v.params["hatch_pattern"]))
            c.currentIndexChanged.connect(lambda i: v.params.__setitem__("hatch_pattern", list(HATCH_PATTERNS)[i]))
            self.form.insertRow(0, "Материал", c)
        if t == "offset":
            cb = QCheckBox("весь замкнутый контур")
            cb.setChecked(v.params["offset_whole"])
            cb.toggled.connect(lambda on: v.params.__setitem__("offset_whole", on))
            self.form.addRow("", cb)
        if t == "mirror":
            cb = QCheckBox("оставить исходные объекты")
            cb.setChecked(v.params["mirror_keep"])
            cb.toggled.connect(lambda on: v.params.__setitem__("mirror_keep", on))
            self.form.addRow("", cb)
        if t == "leader":
            le = QLineEdit(v.params["leader_text"])
            le.textChanged.connect(lambda s: v.params.__setitem__("leader_text", s))
            self.form.addRow("Текст на полке", le)
        if t == "rough":
            c = QComboBox()
            c.addItems(["Ra", "Rz"])
            c.setCurrentText(v.params["rough_param"])
            c.currentTextChanged.connect(lambda s: v.params.__setitem__("rough_param", s))
            le = QLineEdit(v.params["rough_value"])
            le.textChanged.connect(lambda s: v.params.__setitem__("rough_value", s))
            self.form.addRow("Параметр", c)
            self.form.addRow("Значение, мкм", le)
        if t == "block":
            from .library import get_block

            pr = v.params
            try:
                name = get_block(pr["blk_id"]).name
            except ValueError:
                name = "—"
            lab = QLabel(f"<b>{name}</b>")
            lab.setWordWrap(True)
            self.form.addRow(lab)
            le = QLineEdit(pr["blk_label"])
            le.setPlaceholderText("QF1, ОП-12, А…")
            le.textChanged.connect(lambda s_: (pr.__setitem__("blk_label", s_), v.viewport().update()))
            self.edits["blk_label"] = le
            self.form.addRow("Маркировка", le)
            rot = self._spin(pr["blk_rot"], -360, 360, lambda x: (pr.__setitem__("blk_rot", x), v.viewport().update()), 1)
            rot.setSingleStep(90)
            self.spins["blk_rot"] = rot
            self.form.addRow("Поворот, °", rot)
            sc = self._spin(pr["blk_scale"], 0.05, 100, lambda x: (pr.__setitem__("blk_scale", x), v.viewport().update()), 3)
            sc.setSingleStep(0.1)
            self.spins["blk_scale"] = sc
            self.form.addRow("Масштаб", sc)
        if t == "pattern_lin":
            b = QPushButton("Применить к выделенным")
            b.setObjectName("primary")
            b.clicked.connect(v.apply_now)
            self.form.addRow(b)
        if t not in FIELDS:
            from .sketch_view import TOOLS

            lab = QLabel(TOOLS.get(t, ""))
            lab.setWordWrap(True)
            lab.setObjectName("hint")
            self.form.addRow(lab)

    def _line_end_from_polar(self, *_):
        import math

        sp = self.spins
        a = math.radians(sp["angle"].value())
        self._sync("x2", sp["x1"].value() + sp["length"].value() * math.cos(a))
        self._sync("y2", sp["y1"].value() + sp["length"].value() * math.sin(a))

    def _line_polar_from_end(self, *_):
        import math

        sp = self.spins
        dx, dy = sp["x2"].value() - sp["x1"].value(), sp["y2"].value() - sp["y1"].value()
        self._sync("length", math.hypot(dx, dy))
        if dx or dy:
            self._sync("angle", math.degrees(math.atan2(dy, dx)) % 360)

    def _sync(self, key, value):
        s = self.spins.get(key)
        if s is not None and abs(s.value() - value) > 1e-9:
            s.blockSignals(True)
            s.setValue(value)
            s.blockSignals(False)

    def _live(self, values: dict):
        for k, val in values.items():
            s = self.spins.get(k)
            if s is not None and not s.hasFocus():
                self._sync(k, val)
            e = self.edits.get(k)
            if e is not None and not e.hasFocus() and e.text() != val:
                e.blockSignals(True)
                e.setText(val)
                e.blockSignals(False)
        if "r" in values:
            self._sync("d", 2 * values["r"])

    def values(self) -> dict:
        v = {k: s.value() for k, s in self.spins.items()}
        if self.tool == "circle":
            v["by_d"] = self.spins["d"].hasFocus()
        return v

    def apply(self):
        if self.view is not None and self.tool in FIELDS:
            self.view.apply_input(self.values())
