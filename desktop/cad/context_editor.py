"""ПКМ-редактор у курсора и общий конструктор полей для него и для панели «Параметры».

Rows добавляет в QFormLayout поля с мгновенным применением (число — по Enter или при уходе из поля, список и
галочка — сразу) и кнопки действий; всё регистрируется по ключам — так тесты нажимают то же, что пользователь.
ContextEditor — всплывающая панель (Qt.Popup): щелчок мимо закрывает её; после каждой правки она перестраивается
по текущему выделению.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget,
)


class Rows:
    def __init__(self, form: QFormLayout, after=None):
        self.form = form
        self.fields: dict[str, QWidget] = {}
        self.actions: dict[str, QPushButton] = {}
        self.after = after or (lambda: None)   # что сделать после действия (закрыть всплывающую панель)

    def title(self, text):
        lab = QLabel(f"<b>{text}</b>")
        lab.setWordWrap(True)
        self.form.addRow(lab)
        return lab

    def note(self, text):
        lab = QLabel(text)
        lab.setObjectName("hint")
        lab.setWordWrap(True)
        self.form.addRow(lab)
        return lab

    def spin(self, key, label, value, fn, lo=-1e5, hi=1e5, dec=2, step=1.0):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSingleStep(step)
        s.setValue(value)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(fn)
        self.fields[key] = s
        self.form.addRow(label, s)
        return s

    def combo(self, key, label, items, current, fn):
        c = QComboBox()
        for k, lab in items:
            c.addItem(lab, k)
        c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        c.setMinimumContentsLength(10)
        i = c.findData(current)
        c.setCurrentIndex(i)            # -1 — у выбранных разные значения
        c.currentIndexChanged.connect(lambda i: i >= 0 and fn(c.itemData(i)))
        self.fields[key] = c
        self.form.addRow(label, c)
        return c

    def check(self, key, label, on, fn):
        cb = QCheckBox(label)
        cb.setChecked(bool(on))
        cb.toggled.connect(fn)
        self.fields[key] = cb
        self.form.addRow("", cb)
        return cb

    def text(self, key, label, value, fn, placeholder=""):
        le = QLineEdit(value)
        le.setPlaceholderText(placeholder)
        le.editingFinished.connect(lambda: fn(le.text()))
        self.fields[key] = le
        self.form.addRow(label, le)
        return le

    def buttons(self, items, cols=2):
        """Кнопки действий сеткой: (ключ, подпись, функция)."""
        box = QWidget()
        g = QGridLayout(box)
        g.setContentsMargins(0, 2, 0, 0)
        g.setSpacing(3)
        for i, (key, label, fn) in enumerate(items):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, fn=fn: (self.after(), fn()))
            self.actions[key] = b
            g.addWidget(b, i // cols, i % cols)
        self.form.addRow(box)
        return box


class ContextEditor(QFrame):
    """Плавающая панель у курсора. build(rows) заполняет её по текущему выделению; пустое выделение — закрыть."""

    def __init__(self, parent, build):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("contextEditor")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(300)
        self.build = build
        self.form = QFormLayout(self)
        self.form.setContentsMargins(10, 8, 10, 10)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.rows = Rows(self.form, after=self.close)   # кнопка действия закрывает панель (результат — на холсте)
        self._fill()

    @property
    def fields(self):
        return self.rows.fields

    @property
    def actions(self):
        return self.rows.actions

    def _fill(self) -> bool:
        while self.form.rowCount():
            row = self.form.takeRow(0)
            for item in (row.labelItem, row.fieldItem):
                w = item.widget() if item is not None else None
                if w is not None:
                    w.hide()
                    w.deleteLater()
        self.rows.fields, self.rows.actions = {}, {}
        return bool(self.build(self.rows))

    def refresh(self):
        """После правки: панель перестраивается по новому выделению (отложенно — правка могла прийти из её поля)."""
        QTimer.singleShot(0, self._refresh_now)

    def _refresh_now(self):
        if not self.isVisible():
            return
        if not self._fill():
            self.close()
        else:
            self.adjustSize()

    def show_at(self, pos: QPoint):
        self.adjustSize()
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        r = scr.availableGeometry()
        x = min(max(pos.x() + 8, r.left()), r.right() - self.width())
        y = min(max(pos.y() + 8, r.top()), r.bottom() - self.height())
        self.move(x, y)
        self.show()
        first = next((w for w in self.fields.values() if isinstance(w, (QDoubleSpinBox, QLineEdit))), None)
        if first is not None:
            first.setFocus()
            if isinstance(first, QDoubleSpinBox):
                first.selectAll()
