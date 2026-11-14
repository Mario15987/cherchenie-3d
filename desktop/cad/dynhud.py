"""Динамический ввод у курсора: плавающий бейдж с текущими размерами («L: 125.40 мм | ∠: 30.0°») и поля ввода
прямо у перекрестия. Начали печатать цифры — бейдж превращается в поля; Tab переключает поля, Enter фиксирует,
Esc возвращает к мыши. Поле, в которое что-то ввели, «заперто»; остальные продолжают следовать за курсором.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit

OFFSET = QPoint(16, 16)          # от перекрестия — чтобы бейдж его не закрывал
STYLE = ("QFrame#dynHud{background:rgba(20,26,36,225);border:1px solid #3e7bfa;border-radius:5px}"
         "QFrame#dynHud QLabel{color:#ffffff;background:transparent;border:0;padding:0}"
         "QFrame#dynHud QLineEdit{background:#ffffff;color:#101418;border:1px solid #3e7bfa;border-radius:3px;padding:0 3px;"
         "selection-background-color:#3e7bfa;selection-color:#ffffff}"
         "QFrame#dynHud QLineEdit[locked=\"true\"]{background:#fff3c4}")


def fmt_len(v: float) -> str:
    return f"{v:.2f}"


def parse_number(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", ".").replace("°", "").replace("мм", ""))
    except ValueError:
        return None


class DynHud(QFrame):
    committed = Signal(dict)      # {ключ: число} всех полей — Enter
    cancelled = Signal()          # Esc в поле

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("dynHud")
        self.setStyleSheet(STYLE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)   # бейдж не перехватывает щелчки по холсту
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(7, 3, 7, 3)
        self.row.setSpacing(5)
        self.label = QLabel()
        self.row.addWidget(self.label)
        self.fields: dict[str, QLineEdit] = {}
        self._labels: list[QLabel] = []
        self._locked: set[str] = set()
        self.editing = False
        self._anchor = QPoint()
        self.hide()

    # ---------------------------------------------------------------- бейдж
    def text(self) -> str:
        return self.label.text()

    def show_info(self, text: str, pos):
        """Информер у курсора; пока идёт ввод с клавиатуры — только двигается следом."""
        self._anchor = QPoint(int(pos.x()), int(pos.y()))
        if not self.editing:
            if not text:
                self.hide()
                return
            if text != self.label.text():
                self.label.setText(text)
                self.adjustSize()
        self._place()
        self.show()
        self.raise_()

    def hide_info(self):
        if not self.editing:
            self.hide()

    def _place(self):
        p = self._anchor + OFFSET
        par = self.parentWidget()
        if par is not None:      # у края окна — по другую сторону от курсора
            if p.x() + self.width() > par.width():
                p.setX(self._anchor.x() - OFFSET.x() - self.width())
            if p.y() + self.height() > par.height():
                p.setY(self._anchor.y() - OFFSET.y() - self.height())
        self.move(max(0, p.x()), max(0, p.y()))

    # ---------------------------------------------------------------- ввод
    def start_edit(self, fields: list[tuple], first_text: str = ""):
        """fields: (ключ, подпись, значение, единица). first_text — уже нажатая клавиша: ею начинается первое поле."""
        self.stop_edit(silent=True)
        self.editing = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.label.hide()
        for key, label, value, unit in fields:
            lab = QLabel(f"{label}:")
            ed = QLineEdit(fmt_len(value))
            ed.setFixedWidth(64)
            ed.setProperty("unit", unit)
            ed.installEventFilter(self)
            ed.textEdited.connect(lambda _t, k=key: self._lock(k))
            self.row.addWidget(lab)
            self.row.addWidget(ed)
            self._labels.append(lab)
            self.fields[key] = ed
            if unit:
                u = QLabel(unit)
                self.row.addWidget(u)
                self._labels.append(u)
        for wdg in self._labels + list(self.fields.values()):
            wdg.show()           # в уже видимый бейдж Qt показал бы их только после возврата в цикл событий
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        first = next(iter(self.fields.values()))
        first.setFocus()
        if first_text:
            first.setText(first_text)
            self._lock(next(iter(self.fields)))
        else:
            first.selectAll()

    def _lock(self, key):
        self._locked.add(key)
        ed = self.fields[key]
        if ed.property("locked") != "true":
            ed.setProperty("locked", "true")
            ed.style().unpolish(ed)
            ed.style().polish(ed)

    def locked(self) -> set[str]:
        return set(self._locked)

    def follow(self, values: dict):
        """Значения от курсора — в незапертые поля."""
        for key, ed in self.fields.items():
            if key not in self._locked and key in values:
                ed.setText(fmt_len(values[key]))
                if ed.hasFocus():
                    ed.selectAll()

    def values(self) -> dict | None:
        out = {}
        for key, ed in self.fields.items():
            v = parse_number(ed.text())
            if v is None:
                return None
            out[key] = v
        return out

    def stop_edit(self, silent: bool = False):
        was = self.editing
        self.editing = False
        for w in list(self.fields.values()) + self._labels:
            self.row.removeWidget(w)
            w.deleteLater()
        self.fields, self._labels, self._locked = {}, [], set()
        self.label.show()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.adjustSize()
        if was and not silent:
            self.hide()

    def next_field(self, back: bool = False):
        eds = list(self.fields.values())
        if not eds:
            return
        i = next((k for k, e in enumerate(eds) if e.hasFocus()), 0)
        e = eds[(i + (-1 if back else 1)) % len(eds)]
        e.setFocus()
        e.selectAll()

    def commit(self) -> bool:
        v = self.values()
        if v is None:
            return False
        v["_locked"] = self.locked()
        self.stop_edit()
        self.committed.emit(v)
        return True

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.ShortcutOverride and ev.key() in (Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Delete):
            ev.accept()          # клавиша — полю, а не горячим клавишам окна (L, R, Esc…)
            return False
        if t == QEvent.ShortcutOverride and ev.text():
            ev.accept()
            return False
        if t == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Tab, Qt.Key_Backtab):
                self.next_field(back=k == Qt.Key_Backtab or bool(ev.modifiers() & Qt.ShiftModifier))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.commit()
                return True
            if k == Qt.Key_Escape:
                self.stop_edit()
                self.cancelled.emit()
                return True
        return False
