"""Интерфейс модуля ЕСКД: боковая панель-справочник с поиском по номеру и названию ГОСТа, окно нормоконтроля,
табличный редактор спецификации и стартовый экран «Создать»."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import documents, eskd, library
from .dialogs import Ask


def tile_icon(glyph: str, color: QColor, size: int = 34) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.TextAntialiasing)
    f = QFont("Segoe UI Symbol")
    f.setPixelSize(int(size * 1.5))
    p.setFont(f)
    p.setPen(color)
    p.drawText(QRectF(0, 0, size * 2, size * 2), Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


class EskdPanel(QWidget):
    """Справочник: слева вверху поиск и список стандартов по группам, ниже статья и кнопки «сделать в программе»."""
    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("leftPanel")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: 2.104, масштаб, штриховка…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.page = QTextBrowser()
        self.page.setOpenExternalLinks(False)
        self.buttons = QWidget()
        self.grid = QGridLayout(self.buttons)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        self.action_btns: list[QPushButton] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.addWidget(self.search)
        v.addWidget(self.list, 2)
        v.addWidget(self.page, 3)
        v.addWidget(self.buttons)
        self.apply_filter("")

    def apply_filter(self, text: str = ""):
        cur = self.current()
        self.list.blockSignals(True)
        self.list.clear()
        group = None
        first = None
        for g in eskd.search(text):
            if not text.strip() and g["group"] != group:     # без запроса — по группам ЕСКД
                group = g["group"]
                head = QTreeWidgetItem([group])
                head.setFlags(Qt.ItemIsEnabled)
                f = head.font(0)
                f.setBold(True)
                head.setFont(0, f)
                self.list.addTopLevelItem(head)
            it = QTreeWidgetItem([f"ГОСТ {g['num']}  {g['title']}"])
            it.setData(0, Qt.UserRole, g["num"])
            it.setToolTip(0, g["title"])
            self.list.addTopLevelItem(it)
            first = first or it
            if g["num"] == cur:
                first = it
        self.list.blockSignals(False)
        if first is not None:
            self.list.setCurrentItem(first)
        else:
            self.page.setHtml("<p>Ничего не найдено. Попробуйте номер («2.104») или слово из названия.</p>")
            self._buttons([])
        self._show()

    def nums(self) -> list[str]:
        return [self.list.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.list.topLevelItemCount())
                if self.list.topLevelItem(i).data(0, Qt.UserRole)]

    def current(self) -> str | None:
        it = self.list.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def open(self, num: str):
        """Показать стандарт по началу номера («2.104»)."""
        self.search.clear()
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            if (it.data(0, Qt.UserRole) or "").startswith(num):
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it)
                return

    def _show(self):
        g = eskd.by_num(self.current()) if self.current() else None
        if g is None:
            return
        self.page.setHtml(eskd.html_page(g))
        self._buttons(g["actions"])

    def _buttons(self, actions):
        for b in self.action_btns:
            self.grid.removeWidget(b)
            b.deleteLater()
        self.action_btns = []
        for i, (label, key) in enumerate(actions):
            b = QPushButton(label)
            b.setObjectName("preset")
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            self.grid.addWidget(b, i // 2, i % 2)
            self.action_btns.append(b)


LEVEL = {"error": ("✖", "#c22f2f", "Ошибка"), "warn": ("▲", "#b26b00", "Предупреждение"), "ok": ("✔", "#1d7748", "Соответствует")}


class NormDialog(QDialog):
    """Результат нормоконтроля: замечания со ссылкой на ГОСТ; двойной щелчок по замечанию выделяет объекты на листе."""
    showObjects = Signal(list)

    def __init__(self, findings: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Нормоконтроль ЕСКД")
        self.setMinimumSize(640, 420)
        self.findings = findings
        v = QVBoxLayout(self)
        head = QLabel(f"<b>Проверка листа по ЕСКД: {eskd.norm_summary(findings)}</b>")
        v.addWidget(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Стандарт", "Результат"])
        self.tree.setRootIsDecorated(False)
        order = {"error": 0, "warn": 1, "ok": 2}
        for f in sorted(findings, key=lambda f: order[f["level"]]):
            glyph, color, tip = LEVEL[f["level"]]
            it = QTreeWidgetItem([glyph, f["gost"], f["text"]])
            it.setForeground(0, QColor(color))
            it.setToolTip(0, tip)
            it.setData(0, Qt.UserRole, f["ids"])
            if f["ids"]:
                it.setToolTip(2, "Двойной щелчок — показать эти объекты на листе")
            self.tree.addTopLevelItem(it)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.showObjects.emit(it.data(0, Qt.UserRole)) if it.data(0, Qt.UserRole) else None)
        v.addWidget(self.tree, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)


class SpecDialog(QDialog):
    """Табличный редактор спецификации ГОСТ 2.106: раздел, обозначение, наименование, количество, примечание.
    Позиции и порядок разделов расставляются сами при построении таблицы на листе."""
    COLS = [("section", "Раздел"), ("format", "Формат"), ("designation", "Обозначение"), ("name", "Наименование"), ("qty", "Кол."),
            ("note", "Примечание")]

    def __init__(self, rows: list[dict], collect, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Спецификация (ГОСТ 2.106-96)")
        self.setMinimumSize(820, 460)
        self.collect = collect
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([t for _, t in self.COLS])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(2, 170)
        v = QVBoxLayout(self)
        note = QLabel("Разделы: " + ", ".join(eskd.SPEC_SECTIONS) + ". Позиции нумеруются автоматически.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, slot in (("Собрать из чертежа и дерева", self.fill_auto), ("Добавить строку", lambda: self.add_row({})),
                           ("Удалить строку", self.del_row)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Построить на листе")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for r in rows:
            self.add_row(r)

    def add_row(self, r: dict):
        from PySide6.QtWidgets import QComboBox

        i = self.table.rowCount()
        self.table.insertRow(i)
        box = QComboBox()
        box.addItems(eskd.SPEC_SECTIONS)
        box.setCurrentText(r.get("section", "Детали"))
        self.table.setCellWidget(i, 0, box)
        for c, (key, _) in enumerate(self.COLS[1:], 1):
            self.table.setItem(i, c, QTableWidgetItem(str(r.get(key, "1" if key == "qty" and not r else ""))))

    def del_row(self):
        i = self.table.currentRow()
        if i >= 0:
            self.table.removeRow(i)

    def fill_auto(self):
        self.table.setRowCount(0)
        for r in self.collect():
            self.add_row(r)

    def rows(self) -> list[dict]:
        out = []
        for i in range(self.table.rowCount()):
            r = {"section": self.table.cellWidget(i, 0).currentText(), "zone": "", "pos": ""}
            for c, (key, _) in enumerate(self.COLS[1:], 1):
                it = self.table.item(i, c)
                r[key] = it.text().strip() if it is not None else ""
            if r["name"]:
                out.append(r)
        return out


class StartDialog(QDialog):
    """«Создать»: документ или документ по шаблону; ниже — советы с прокруткой."""

    def __init__(self, parent=None, show_at_start: bool = True, tip_index: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Создать")
        self.setMinimumWidth(820)
        self.choice: tuple[str, str] | None = None
        self.tip_index = tip_index % len(documents.TIPS)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        mode = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_btns = []
        for i, text in enumerate(("Документ", "Документ по шаблону")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.mode_group.addButton(b, i)
            mode.addWidget(b)
            self.mode_btns.append(b)
        mode.addStretch(1)
        v.addLayout(mode)
        self.stack = QStackedWidget()
        self.mode_group.idClicked.connect(self.stack.setCurrentIndex)
        v.addWidget(self.stack, 1)

        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        self.doc_btns: dict[str, QToolButton] = {}
        for caption, items in (("Основные документы", documents.DOCS), ("Специальный документ", documents.PROFILES)):
            cap = QLabel(caption)
            cap.setObjectName("groupCaption")
            pv.addWidget(cap)
            row = QHBoxLayout()
            row.setSpacing(6)
            for key, title, glyph, tip in items:
                b = QToolButton()
                b.setObjectName("docTile")
                b.setText(title)
                b.setIcon(tile_icon(glyph, self.palette().color(self.foregroundRole())))
                b.setIconSize(QSize(34, 34))
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setToolTip(tip)
                b.setFixedSize(110, 92)
                b.clicked.connect(lambda _=False, k=key: self._pick("doc", k))
                row.addWidget(b)
                self.doc_btns[key] = b
            row.addStretch(1)
            pv.addLayout(row)
        pv.addStretch(1)
        self.stack.addWidget(page)

        tpl = QWidget()
        tv = QVBoxLayout(tpl)
        tv.setContentsMargins(0, 0, 0, 0)
        self.templates = QListWidget()
        for t in library.TEMPLATES.values():
            it = QListWidgetItem(f"{t.name}   —   {library.SECTIONS[t.section].split(' (')[0]}")
            it.setData(Qt.UserRole, t.id)
            self.templates.addItem(it)
        self.templates.itemDoubleClicked.connect(lambda it: self._pick("template", it.data(Qt.UserRole)))
        tv.addWidget(self.templates, 1)
        open_btn = QPushButton("Создать по шаблону")
        open_btn.clicked.connect(lambda: self._pick("template", self.templates.currentItem().data(Qt.UserRole)) if self.templates.currentItem() else None)
        tv.addWidget(open_btn, 0, Qt.AlignRight)
        self.stack.addWidget(tpl)

        tips = QWidget()
        tips.setObjectName("tipBox")
        th = QHBoxLayout(tips)
        th.setContentsMargins(10, 8, 10, 8)
        col = QVBoxLayout()
        head = QLabel("<b>Знаете ли вы, что:</b>")
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        self.tip.setMinimumHeight(38)
        col.addWidget(head)
        col.addWidget(self.tip)
        th.addLayout(col, 1)
        self.prev_btn, self.next_btn = QPushButton("<<"), QPushButton(">>")
        for b, step in ((self.prev_btn, -1), (self.next_btn, 1)):
            b.setFixedWidth(40)
            b.setToolTip("Предыдущий совет" if step < 0 else "Следующий совет")
            b.clicked.connect(lambda _=False, s=step: self.turn_tip(s))
            th.addWidget(b, 0, Qt.AlignBottom)
        v.addWidget(tips)
        foot = QHBoxLayout()
        self.at_start = QCheckBox("Показывать при запуске")
        self.at_start.setChecked(show_at_start)
        foot.addWidget(self.at_start)
        foot.addStretch(1)
        cancel = QPushButton("Закрыть")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        v.addLayout(foot)
        self.turn_tip(0)

    def turn_tip(self, step: int):
        self.tip_index = (self.tip_index + step) % len(documents.TIPS)
        self.tip.setText(documents.TIPS[self.tip_index])

    def _pick(self, kind: str, key: str):
        self.choice = (kind, key)
        self.accept()


def run_start_dialog(parent, show_at_start=True, tip_index=0):
    """(выбор, показывать при запуске, номер совета); выбор — ("doc", ключ), ("template", id) или None."""
    dlg = StartDialog(parent, show_at_start, tip_index)
    if Ask.AUTO:
        Ask.answers.setdefault("_forms", []).append(dlg.windowTitle())
        choice = Ask.answers.get("start.choice")
        dlg.deleteLater()
        return choice, show_at_start, tip_index
    dlg.exec()
    return dlg.choice, dlg.at_start.isChecked(), dlg.tip_index + 1
