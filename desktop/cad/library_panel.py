"""Боковая панель «Библиотека»: поиск, шаблоны листов (уровень А), каталог элементов и УГО (уровень Б), «Мои элементы».

Значки и превью — векторные (cad.preview), в цветах текущей темы. Двойной щелчок по элементу — вставка на чертёж,
по шаблону — новый документ из шаблона.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import library
from .model import Project, sheet_size
from .preview import render_pixmap

ICON = 30   # значок элемента в дереве, px


class LibraryPanel(QWidget):
    insertBlock = Signal(str)
    openTemplate = Signal(str)
    saveSelection = Signal()
    deleteUser = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiPanel")
        self.icon_ink, self.ink, self.paper = QColor("#2c3a4d"), QColor("#14181e"), QColor("#fbfbf8")
        self._tpl_cache: dict[str, Project] = {}
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: автомат, опора, изолятор, дверь, швеллер…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(ICON, ICON))
        self.tree.setStyleSheet(f"QTreeWidget::item {{ height: {ICON + 4}px; }}")   # тема задаёт 22 px — значок не влезал
        self.tree.currentItemChanged.connect(lambda *_: self._show_current())
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.activate(it))
        self.preview = QLabel()
        self.preview.setMinimumHeight(170)
        self.preview.setAlignment(Qt.AlignCenter)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("hint")
        self.go = QPushButton("Вставить на чертёж")
        self.go.setObjectName("primary")
        self.go.clicked.connect(lambda: self.activate(self.tree.currentItem()))
        self.save_btn = QPushButton("Сохранить выделенное в библиотеку")
        self.save_btn.setToolTip("Выделите на холсте свой узел — он появится в «Моих элементах» (user_library.json рядом с программой)")
        self.save_btn.clicked.connect(self.saveSelection)
        self.del_btn = QPushButton("Удалить из «Моих»")
        self.del_btn.clicked.connect(self._delete_current)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.addWidget(self.search)
        v.addWidget(self.tree, 1)
        v.addWidget(self.preview)
        v.addWidget(self.info)
        row = QHBoxLayout()
        row.addWidget(self.go, 1)
        row.addWidget(self.del_btn)
        v.addLayout(row)
        v.addWidget(self.save_btn)
        self.rebuild()

    # ------------------------------------------------------------ содержимое
    def rebuild(self):
        """Заполнить дерево заново (после «Сохранить в библиотеку» или смены темы)."""
        cur = self.current_key()
        self.tree.clear()
        self.items: dict[tuple, QTreeWidgetItem] = {}
        tpl_root = self._node(None, "Шаблоны листов", "Готовые листы А4/А3 со штампом, таблицами и сеткой")
        for sec, title in library.SECTIONS.items():
            tpls = [t for t in library.TEMPLATES.values() if t.section == sec]
            if not tpls:
                continue
            node = self._node(tpl_root, title)
            for t in tpls:
                it = QTreeWidgetItem([t.name])
                it.setData(0, Qt.UserRole, ("template", t.id))
                it.setIcon(0, self._sheet_icon(t.canvas))
                it.setToolTip(0, f"{t.name}\nДвойной щелчок — открыть новый документ из шаблона")
                node.addChild(it)
                self.items[("template", t.id)] = it
        blk_root = self._node(None, "Элементы и УГО", "Двойной щелчок — прикрепить к курсору и поставить щелчком")
        blocks = library.all_blocks()
        for sec, title in library.SECTIONS.items():
            sec_blocks = [b for b in blocks if b.section == sec]
            if not sec_blocks and sec != "user":
                continue
            node = self._node(blk_root, title)
            groups: dict[str, QTreeWidgetItem] = {}
            for b in sec_blocks:
                parent = node if sec == "user" else groups.get(b.group) or groups.setdefault(b.group, self._node(node, b.group))
                it = QTreeWidgetItem([b.name])
                it.setData(0, Qt.UserRole, ("block", b.id))
                it.setIcon(0, self.block_icon(b.id))
                it.setToolTip(0, f"{b.name}\n{library.SECTIONS[sec]}" + (f"\nМаркировка: {b.label}" if b.label else ""))
                parent.addChild(it)
                self.items[("block", b.id)] = it
            if sec == "user" and not sec_blocks:
                hint = QTreeWidgetItem(["пусто — выделите узел и нажмите «Сохранить выделенное»"])
                hint.setDisabled(True)
                node.addChild(hint)
        tpl_root.setExpanded(True)
        blk_root.setExpanded(True)
        self.apply_filter(self.search.text())
        if cur in self.items:
            self.tree.setCurrentItem(self.items[cur])

    def _node(self, parent, text, tip=""):
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole, ("node", text))
        f = it.font(0)
        f.setBold(parent is None)
        it.setFont(0, f)
        if tip:
            it.setToolTip(0, tip)
        (parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it))
        return it

    def block_icon(self, bid: str) -> QIcon:
        ents = library.instantiate(bid, label="")
        return QIcon(render_pixmap(ents, ICON, self.icon_ink, library.bounds(ents), main_px=1.3, thin_px=0.8))

    def _sheet_icon(self, canvas: str) -> QIcon:
        from .model import CANVAS_MODES

        _, fmt, orient = CANVAS_MODES[canvas]
        w, h = sheet_size(fmt, orient)
        ink = self.icon_ink

        def frame(p):
            pen = QPen(ink, 0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawRect(QRectF(0, 0, w, h))
            p.drawRect(QRectF(20, 5, w - 25, h - 10))
            p.drawRect(QRectF(w - 190, 5, 185, 55))
            for k in range(4):   # «строки» содержимого
                p.drawLine(30, h - 25 - k * 18, 30 + (w - 60) * (0.8 - 0.15 * k), h - 25 - k * 18)
        return QIcon(render_pixmap([], ICON, ink, (0, 0, w, h), extra=frame))

    def apply_theme(self, icon_ink, ink, paper):
        """Значки — цветом текста панели, превью — цветами листа чертежа."""
        self.icon_ink, self.ink, self.paper = QColor(icon_ink), QColor(ink), QColor(paper)
        self._tpl_cache.clear()
        self.rebuild()

    # ------------------------------------------------------------ поиск и выбор
    def apply_filter(self, text: str):
        """Скрыть всё, что не подходит под запрос; разделы с найденным раскрыть."""
        query = text.strip()
        hits = None
        if query:
            hits = {("block", b.id) for b in library.search(query, library.all_blocks())}
            hits |= {("template", t.id) for t in library.search(query, library.TEMPLATES.values())}
        first = None
        for key, it in self.items.items():
            show = hits is None or key in hits
            it.setHidden(not show)
            if show and hits is not None and first is None:
                first = it
        self._hide_empty(self.tree.invisibleRootItem(), bool(query))
        if first is not None:
            self.tree.setCurrentItem(first)
        self._show_current()

    def _hide_empty(self, node, expand) -> bool:
        """Узел виден, если в нём есть видимые элементы. При поиске — раскрыть."""
        any_visible = False
        for i in range(node.childCount()):
            ch = node.child(i)
            kind = (ch.data(0, Qt.UserRole) or ("", ""))[0]
            if kind == "node":
                vis = self._hide_empty(ch, expand)
                ch.setHidden(not vis)
                if expand and vis:
                    ch.setExpanded(True)
            else:
                vis = not ch.isHidden() and not ch.isDisabled()
            any_visible |= vis
        return any_visible

    def visible_keys(self) -> list[tuple]:
        return [k for k, it in self.items.items() if not it.isHidden() and all(not p.isHidden() for p in _parents(it))]

    def current_key(self):
        it = self.tree.currentItem() if hasattr(self, "tree") else None
        d = it.data(0, Qt.UserRole) if it is not None else None
        return tuple(d) if d and d[0] in ("block", "template") else None

    def select(self, kind: str, key: str):
        it = self.items.get((kind, key))
        if it is not None:
            self.tree.setCurrentItem(it)

    def _show_current(self):
        key = self.current_key()
        self.go.setEnabled(key is not None)
        self.del_btn.setVisible(bool(key and key[0] == "block" and key[1].startswith("user_")))
        if key is None:
            self.preview.clear()
            self.info.setText("Выберите шаблон листа или элемент. Поиск — по названию и ключевым словам.")
            return
        kind, kid = key
        if kind == "block":
            b = library.get_block(kid)
            ents = library.instantiate(kid)
            self.preview.setPixmap(render_pixmap(ents, (260, 160), self.ink, library.bounds(ents), bg=self.paper))
            ports = ", ".join(b.ports) or "—"
            self.info.setText(f"<b>{b.name}</b><br>{library.SECTIONS[b.section]} · {b.group}<br>Выводы: {ports}"
                              + (f"<br>Маркировка: {b.label}" if b.label else ""))
            self.go.setText("Вставить на чертёж")
        else:
            t = library.TEMPLATES[kid]
            pr = self._template_project(kid)
            self.preview.setPixmap(self._sheet_pixmap(pr, (260, 170)))
            self.info.setText(f"<b>{t.name}</b><br>{library.SECTIONS[t.section]} · лист {pr.frame['format']}, М {pr.frame['scale']}")
            self.go.setText("Открыть шаблон")

    def _template_project(self, tid) -> Project:
        if tid not in self._tpl_cache:
            pr = Project()
            library.load_template(pr, tid)
            self._tpl_cache[tid] = pr
        return self._tpl_cache[tid]

    def _sheet_pixmap(self, pr: Project, size):
        from .model import make_line, make_text
        from .stamp import frame_geometry

        w, h = sheet_size(pr.frame["format"], pr.frame["orient"])
        lines, texts = frame_geometry(pr.frame, pr)
        fr = [make_line(*ln[:4], "main" if ln[4] == "main" else "thin") for ln in lines]
        fr += [make_text(x, y, s, hh, 0, al) for x, y, hh, s, al in texts]
        return render_pixmap(fr + pr.drawing, size, self.ink, (0, 0, w, h), bg=self.paper, main_px=1.0, thin_px=0.6)

    def activate(self, it):
        d = it.data(0, Qt.UserRole) if it is not None else None
        if not d:
            return
        if d[0] == "block":
            self.insertBlock.emit(d[1])
        elif d[0] == "template":
            self.openTemplate.emit(d[1])

    def _delete_current(self):
        key = self.current_key()
        if key and key[0] == "block" and key[1].startswith("user_"):
            self.deleteUser.emit(key[1])


def _parents(it):
    p = it.parent()
    while p is not None:
        yield p
        p = p.parent()

