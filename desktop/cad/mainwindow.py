"""Главное окно: лента, дерево построения, параметры, эскиз, лист чертежа, 3D, ИИ-помощник, файлы .k3d."""
from __future__ import annotations

import html
import json
import os
import time

import numpy as np

from PySide6.QtCore import QRectF, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QTabBar, QTabWidget, QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import ai, attachments, edit2d, geometry as geo, library, ops, params, selection
from .chat_panel import AttachmentBar, AttachWorker, ChatInput, DropCatcher, png_bytes
from .context_editor import ContextEditor, Rows
from .appearance import AppearanceDialog
from .dialogs import AISettingsDialog, Ask, ask_form, quick_edit, warn
from .dims import check_tolerance
from .export2d import drawing_bounds, to_dxf, to_svg
from .inputpanel import ToolPanel
from .library_panel import LibraryPanel
from .model import (
    CANVAS_MODES, FEATURE_LABEL, FORMATS, HATCH_PATTERNS, STAMP_ROLES, STYLE_LABEL, STYLES, History, Project, default_frame,
    entity_label,
)
from .projection import SCALES, make_drawing
from .resources import APP_NAME, icon_path
from .sketch_view import SNAP_KINDS, SketchView
from .themes import ThemeManager, mix, readable
from .view3d import View3D

APP = APP_NAME
FILTER = f"Проект «{APP}» (*.k3d)"
OPS = [("add", "объединение"), ("cut", "вычитание"), ("intersect", "пересечение")]
FIELD_NAMES = {"x1": "X1", "y1": "Y1", "x2": "X2", "y2": "Y2", "cx": "Центр X", "cy": "Центр Y", "r": "Радиус", "a0": "Угол начала",
               "a1": "Угол 1", "a2": "Угол 2", "off": "Вынос", "ang": "Угол полки", "rad": "Радиус дуги", "x": "X", "y": "Y",
               "step": "Шаг", "angle": "Угол"}
FEATURE_GLYPH = {"extrude": "⬆", "revolve": "⟳", "shell": "▢", "fillet3d": "◜", "chamfer3d": "◸"}


def glyph_icon(glyph: str, color: str = "#2c3a4d") -> QIcon:
    """Иконка из символа: без графических файлов и чужих наборов иконок."""
    pm = QPixmap(44, 44)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.TextAntialiasing)
    f = QFont("Segoe UI Symbol")
    f.setPixelSize(30)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, 44, 44), Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(str(icon_path())))
        self.project = Project()
        self.history = History(self.project)
        self.path: str | None = None
        self.dirty = False
        self.solid = geo.build_solid([])
        self.chat: list[dict] = []
        self.worker: ai.AIWorker | None = None
        self.attachments: list[attachments.Attachment] = []      # прикреплено к следующему сообщению
        self._sent_attachments: list[attachments.Attachment] = []
        self._attach_workers: list[AttachWorker] = []
        self._pending_preset: str | None = None
        self._attach_seq = 0
        self.sel_feature: str | None = None          # операция, выбранная в дереве или щелчком по грани в 3D
        self._manip_anchor: tuple | None = None      # точка грани (x, y), от которой растёт стрелка
        self._ghost_slow = False
        self.cfg = ai.load_config()
        self._init_canvas(self.project)
        self.themes = ThemeManager(self.cfg.get("appearance", {}), self.cfg.get("active_theme"))
        self.glyph_buttons: list[tuple[QToolButton, str]] = []
        self.ribbon_actions: dict[str, QToolButton] = {}   # все кнопки ленты — для автотеста
        self.appearance_dlg: AppearanceDialog | None = None
        self.edit_fid: str | None = None                   # операция, чей эскиз открыт на редактирование
        self.ctx_editor: ContextEditor | None = None       # ПКМ-редактор у курсора
        self._clipboard: list[dict] = []                   # Ctrl+C / Ctrl+V

        # Поля сразу в цветах сохранённой темы — без вспышки светлых цветов по умолчанию.
        self.sketch = SketchView(self.project, "sketch", theme=self.themes.theme)
        self.sheet = SketchView(self.project, "drawing", theme=self.themes.theme)
        self.view3d = View3D(theme=self.themes.theme)
        self.work = QTabWidget()
        self.work.setDocumentMode(True)
        self.work.addTab(self.sketch, "✎  Эскиз")
        self.work.addTab(self.sheet, "▤  Чертёж")
        self.work.addTab(self.view3d, "⬢  3D-модель")
        self.work.currentChanged.connect(self._on_tab)

        self.banner = QWidget()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(8, 4, 8, 4)
        self.banner_label = QLabel()
        done = QPushButton("Закончить редактирование эскиза")
        done.setObjectName("primary")
        done.clicked.connect(self.finish_sketch_edit)
        bl.addWidget(self.banner_label, 1)
        bl.addWidget(done)
        self.banner.hide()

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._ribbon())
        lay.addWidget(self.banner)
        lay.addWidget(self.work, 1)
        self.setCentralWidget(central)

        self._left_dock()
        self._ai_dock()
        self._library_dock()
        self._menus()
        self._status()

        for v in (self.sketch, self.sheet):
            v.editStarted.connect(lambda: self.history.push())
            v.edited.connect(self._sketch_edited)
            v.editFailed.connect(lambda: self.history.undo_stack.pop() if self.history.undo_stack else None)
            v.selectionChanged.connect(self._on_sketch_selection)
            v.cursorMoved.connect(lambda x, y, s: self.coord.setText(f"X {x:9.2f}   Y {y:9.2f}   {s}"))
            v.hint.connect(self.hint.setText)
            v.editEntity.connect(self.edit_entity)
            v.stampField.connect(self.edit_stamp)
            v.contextRequested.connect(lambda pos, v=v: self.open_context_editor(v, pos))
            v.toolEnded.connect(lambda: self.set_tool("select"))
            for seq, fn in (("Ctrl+A", lambda v=v: v.select_all()), ("Ctrl+C", self.copy_selection), ("Ctrl+V", self.paste)):
                QShortcut(QKeySequence(seq), v, activated=fn, context=Qt.WidgetWithChildrenShortcut)
            for key, tool in (("L", "line"), ("R", "rect"), ("C", "circle"), ("A", "arc"), ("D", "dim_a"), ("S", "select"), ("T", "trim")):
                QShortcut(QKeySequence(key), v, activated=lambda t=tool, v=v: self._hotkey(v, t), context=Qt.WidgetWithChildrenShortcut)
            QShortcut(QKeySequence(Qt.Key_Escape), v, activated=lambda v=v: (v.cancel(), self._sync_tool_buttons(v.tool)), context=Qt.WidgetWithChildrenShortcut)

        self.view3d.faceClicked.connect(self._on_face_clicked)
        self.view3d.faceDoubleClicked.connect(self._on_face_double)
        manip = self.view3d.manip
        manip.moved.connect(self._on_handle_moved)
        manip.released.connect(self._on_handle_released)
        manip.cancelled.connect(self._on_handle_cancelled)
        manip.editRequested.connect(lambda: self.quick_edit_feature(self.sel_feature) if self.sel_feature else None)

        self.resize(1440, 900)
        st = QSettings("ReCAD", "desktop")
        if st.value("geometry") and not Ask.AUTO:
            self.restoreGeometry(st.value("geometry"))
        self.themes.changed.connect(self._on_theme)
        self.themes.apply()
        self.refresh()
        self.set_tool("select")
        self.hint.setText(f"«{APP}» готово к работе: выберите инструмент на ленте или опишите задачу ИИ-помощнику (Ctrl+I)")

    # ================================================================ интерфейс
    def _ribbon(self) -> QTabWidget:
        rib = QTabWidget()
        rib.setObjectName("ribbon")
        rib.setFixedHeight(104)
        self.tool_buttons: dict[str, QToolButton] = {}

        def page(groups):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 2, 4, 0)
            h.setSpacing(2)
            for title, items in groups:
                g = QWidget()
                v = QVBoxLayout(g)
                v.setContentsMargins(3, 0, 3, 0)
                v.setSpacing(0)
                row = QHBoxLayout()
                row.setSpacing(1)
                for b in items:
                    row.addWidget(b)
                v.addLayout(row)
                cap = QLabel(title)
                cap.setAlignment(Qt.AlignCenter)
                cap.setObjectName("groupCaption")
                v.addWidget(cap)
                h.addWidget(g)
                sep = QWidget()
                sep.setFixedWidth(1)
                sep.setObjectName("sep")
                h.addWidget(sep)
            h.addStretch(1)
            return w

        def btn(glyph, text, slot, tip="", checkable=False, key=None):
            b = QToolButton()
            b.setText(text)
            b.setIcon(glyph_icon(glyph))
            self.glyph_buttons.append((b, glyph))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip or text.replace("-\n", "").replace("\n", " "))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setFixedSize(68, 62)
            b.setCheckable(checkable)
            b.clicked.connect(slot)
            if key:
                self.tool_buttons[key] = b
            self.ribbon_actions[text.replace("-\n", "").replace("\n", " ")] = b
            return b

        def tool(glyph, text, name, key=""):
            return btn(glyph, text, lambda: self.set_tool(name), f"{text.replace(chr(10), ' ')}" + (f" ({key})" if key else ""), True, name)

        self.style_box = QComboBox()
        for k in STYLES:
            self.style_box.addItem(STYLE_LABEL[k], k)
        self.style_box.setMinimumWidth(190)
        self.style_box.currentIndexChanged.connect(self._set_style)
        style_w = QWidget()
        sv = QVBoxLayout(style_w)
        sv.setContentsMargins(0, 8, 0, 0)
        sv.addWidget(self.style_box)
        sv.addStretch(1)

        self.snap_btn = btn("◎", "Привязки", lambda: self.snap_btn.showMenu(), "Объектные привязки")
        self.snap_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.snap_btn)
        self.snap_actions = {}
        for k, lab in SNAP_KINDS.items():
            a = menu.addAction(lab)
            a.setCheckable(True)
            a.setChecked(True)
            a.toggled.connect(self._set_snaps)
            self.snap_actions[k] = a
        self.snap_btn.setMenu(menu)

        rib.addTab(page([
            ("Выбор", [tool("↖", "Выбор", "select", "S")]),
            ("Геометрия", [tool("╱", "Отрезок", "line", "L"), tool("▭", "Прямо-\nугольник", "rect", "R"),
                           tool("◯", "Окруж-\nность", "circle", "C"), tool("◠", "Дуга", "arc", "A"), tool("┄", "Осевая", "axis")]),
            ("Тип линии (ГОСТ 2.303)", [style_w]),
            ("Привязки", [self.snap_btn]),
        ]), "Эскиз")
        rib.addTab(page([
            ("Кривые", [tool("✂", "Усечь", "trim", "T"), tool("⟶", "Удлинить", "extend"),
                        tool("◸", "Фаска", "chamfer"), tool("◜", "Скруг-\nление", "fillet"), tool("⇔", "Экви-\nдистанта", "offset")]),
            ("Копии", [tool("⇋", "Симмет-\nрия", "mirror"), tool("⣿", "Массив\nсетка", "pattern_lin"), tool("✲", "Массив\nкруг", "pattern_circ")]),
            ("Контур", [btn("⛓", "Замкнуть\nконтуры", self.close_contours, "Свести разрывы до 1 мм между концами отрезков"),
                        btn("✕", "Удалить", self.delete_selected, "Удалить выделенное (Delete)")]),
        ]), "Редактирование")
        rib.addTab(page([
            ("Размеры (ГОСТ 2.307)", [tool("↔", "Гори-\nзонт.", "dim_h"), tool("↕", "Верти-\nкальн.", "dim_v"), tool("⤢", "Парал-\nлельн.", "dim_a", "D"),
                                      tool("⌀", "Диаметр", "dim_dia"), tool("R", "Радиус", "dim_rad"), tool("∠", "Угловой", "dim_ang")]),
            ("Обозначения", [tool("↗", "Выноска", "leader"), tool("√", "Шерохо-\nватость", "rough"), tool("▨", "Штри-\nховка", "hatch")]),
        ]), "Оформление")
        rib.addTab(page([
            ("Элементы тела", [btn("⬆", "Выдавли-\nвание", self.extrude, "Выдавить замкнутые контуры эскиза"),
                               btn("⬇", "Вырез", self.cut, "Вырезать выдавливанием"),
                               btn("⟳", "Враще-\nние", self.revolve, "Тело вращения вокруг осевой линии эскиза")]),
            ("Обработка", [btn("▢", "Оболочка", self.shell), btn("◜", "Скругл.\nрёбер", lambda: self.edge3d("fillet3d")),
                           btn("◸", "Фаска\nрёбер", lambda: self.edge3d("chamfer3d"))]),
            ("Вид", [btn("◈", "Изомет-\nрия", lambda: self._view3d("iso")), btn("▣", "Спереди", lambda: self._view3d("front")),
                     btn("▤", "Сверху", lambda: self._view3d("top")), btn("⤢", "Показать\nвсё", self._fit)]),
            ("Файл", [btn("⇩", "STL", lambda: self.export_mesh("stl")), btn("⇩", "OBJ", lambda: self.export_mesh("obj"))]),
        ]), "Моделирование")
        self.canvas_box = QComboBox()
        for k, (label, _, _) in CANVAS_MODES.items():
            self.canvas_box.addItem(label, k)
        self.canvas_box.setMinimumWidth(270)
        self.canvas_box.setToolTip("Формат полотна: бесконечное поле (фрагмент) или лист с рамкой и штампом ГОСТ 2.104")
        self.canvas_box.currentIndexChanged.connect(lambda i: self.set_canvas(self.canvas_box.itemData(i)))
        canvas_w = QWidget()
        cv = QVBoxLayout(canvas_w)
        cv.setContentsMargins(0, 8, 0, 0)
        cv.addWidget(self.canvas_box)
        cv.addStretch(1)
        rib.addTab(page([
            ("Формат полотна", [canvas_w, btn("⛶", "Вписать\nлист", self.fit_sheet, "Вписать лист в окно")]),
            ("Лист", [btn("⊡", "Формат\nи рамка", self.edit_frame), tool("⌖", "Положение\nрамки", "frame"),
                      btn("✎", "Основная\nнадпись", lambda: self.edit_stamp("name"))]),
            ("Виды", [btn("⧉", "Чертёж\nпо модели", self.drawing_from_model, "Три вида (спереди, сверху, слева) с габаритами")]),
            ("Файл", [btn("⇩", "DXF", self.export_dxf), btn("⇩", "SVG", self.export_svg)]),
        ]), "Чертёж")
        rib.addTab(page([
            ("Каталог ГОСТ / СПДС / ЕСКД", [btn("▦", "Каталог\nэлементов", self.show_library, "Библиотека шаблонов и элементов (Ctrl+B)"),
                                            btn("⊞", "Шаблон\nлиста", self.choose_template, "Новый документ из готового шаблона листа")]),
            ("Мои элементы", [btn("⤓", "Сохранить\nв библ.", self.save_to_library, "Сохранить выделенное в «Мои элементы»")]),
        ]), "Библиотека")
        rib.addTab(page([
            ("Помощник", [btn("✦", "ИИ-\nпомощник", self.show_ai, "Чат ИИ-помощника (Ctrl+I)"),
                          btn("⚙", "Настройки\nИИ", self.ai_settings)]),
        ]), "ИИ")
        palette = QToolButton()
        palette.setText("🎨")
        palette.setToolTip("Внешний вид и цветовые темы")
        palette.setAccessibleName("Внешний вид и цветовые темы")
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(18)
        palette.setFont(f)
        palette.setFixedSize(34, 26)
        palette.clicked.connect(self.show_appearance)
        rib.setCornerWidget(palette, Qt.TopRightCorner)
        return rib

    def _left_dock(self):
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemDoubleClicked.connect(self._on_tree_double)
        self.props = QWidget()
        self.props_form = QFormLayout(self.props)
        self.props_form.setLabelAlignment(Qt.AlignRight)
        self.tool_panel = ToolPanel()
        self.lower = QStackedWidget()
        self.lower.addWidget(self._titled("Параметры", self.props))
        self.lower.addWidget(self.tool_panel)
        split = QSplitter(Qt.Vertical)
        split.setObjectName("leftPanel")
        split.addWidget(self._titled("Дерево построения", self.tree))
        split.addWidget(self.lower)
        split.setSizes([420, 380])
        split.setMinimumWidth(270)
        dock = QDockWidget("Модель", self)
        dock.setObjectName("left")
        dock.setWidget(split)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [300], Qt.Horizontal)

    @staticmethod
    def _titled(title, w):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        cap = QLabel(title.upper())
        cap.setObjectName("panelTitle")
        v.addWidget(cap)
        v.addWidget(w, 1)
        return box

    def _ai_dock(self):
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        self.chat_input = ChatInput()
        self.chat_input.setPlaceholderText("Например: «нарисуй фланец 80×80 с отверстием Ø30 и четырьмя Ø8 по окружности Ø60 и выдави "
                                           "на 10 мм». Фото чертежа, детали или файл Word — кнопкой 📎, перетаскиванием или Ctrl+V. "
                                           "Ctrl+Enter — отправить")
        self.chat_input.setFixedHeight(84)
        self.chat_input.filesDropped.connect(self.attach_files)
        self.chat_input.imagePasted.connect(self.attach_image)
        QShortcut(QKeySequence("Ctrl+Return"), self.chat_input, activated=self.ai_send)
        self.ai_apply = QCheckBox("Сразу выполнять команды ИИ")
        self.ai_apply.setChecked(True)
        self.ai_status = QLabel("")
        self.ai_status.setWordWrap(True)
        self.ai_send_btn = QPushButton("Отправить")
        self.ai_send_btn.clicked.connect(lambda: self.ai_send())
        self.ai_attach_btn = QPushButton("📎 Прикрепить")
        self.ai_attach_btn.setToolTip("Фото чертежа или детали (PNG, JPG, WEBP, BMP), Word (.docx), текст (.txt, .csv, .json).\n"
                                      "Файлы можно перетащить в чат, скриншот — вставить в поле Ctrl+V")
        self.ai_attach_btn.clicked.connect(lambda: self.attach_dialog())
        settings = QPushButton("Настройки…")
        settings.setToolTip("Провайдер, модель и API-ключ")
        settings.clicked.connect(self.ai_settings)
        self.ai_settings_btn = settings
        self.attach_bar = AttachmentBar()
        self.attach_bar.removed.connect(self.remove_attachment)
        presets = QWidget()
        pv = QVBoxLayout(presets)
        pv.setContentsMargins(0, 2, 0, 2)
        pv.setSpacing(3)
        cap = QLabel("Быстрые сценарии с вложением")
        cap.setObjectName("groupCaption")
        pv.addWidget(cap)
        self.ai_preset_btns: dict[str, QPushButton] = {}
        for key, label, need, prompt in ai.ATTACH_PRESETS:
            b = QPushButton(label)
            b.setObjectName("preset")
            b.setToolTip(prompt + ("\nНет фото во вложениях — откроется выбор файла." if need == "image"
                                   else "\nНет документа во вложениях — откроется выбор файла .docx."))
            b.clicked.connect(lambda _=False, k=key: self.ai_preset(k))
            pv.addWidget(b)
            self.ai_preset_btns[key] = b
        w = QWidget()
        w.setObjectName("aiPanel")
        self.ai_panel = w
        self._drop = DropCatcher(self)
        self._drop.filesDropped.connect(self.attach_files)
        self._drop.imageDropped.connect(self.attach_image)
        self._drop.hovering.connect(self._drop_hover)
        for target in (w, self.chat_view.viewport(), self.chat_input.viewport()):
            target.setAcceptDrops(True)
            target.installEventFilter(self._drop)
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.addWidget(self.chat_view, 1)
        v.addWidget(presets)
        v.addWidget(self.attach_bar)
        v.addWidget(self.chat_input)
        row = QHBoxLayout()
        row.addWidget(self.ai_attach_btn)
        row.addStretch(1)
        row.addWidget(settings)
        row.addWidget(self.ai_send_btn)
        v.addLayout(row)
        v.addWidget(self.ai_apply)
        v.addWidget(self.ai_status)
        self.ai_dock = QDockWidget("ИИ-помощник", self)
        self.ai_dock.setObjectName("ai")
        self.ai_dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, self.ai_dock)
        self.resizeDocks([self.ai_dock], [320], Qt.Horizontal)
        self._chat_note(f"Здравствуйте! Это ИИ-помощник «{APP}». Опишите, что начертить или построить. Помощник видит эскиз, контуры и дерево построения "
                        "и отвечает командами, которые сразу выполняются (их можно отменить Ctrl+Z). "
                        "Можно приложить фото чертежа или детали и документ Word — помощник начертит по ним.")

    def _library_dock(self):
        self.library_panel = LibraryPanel()
        self.library_panel.insertBlock.connect(self.insert_block)
        self.library_panel.openTemplate.connect(self.open_template)
        self.library_panel.saveSelection.connect(self.save_to_library)
        self.library_panel.deleteUser.connect(self.delete_user_block)
        self.library_dock = QDockWidget("Библиотека", self)
        self.library_dock.setObjectName("library")
        self.library_dock.setWidget(self.library_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.library_dock)
        self.tabifyDockWidget(self.ai_dock, self.library_dock)
        self.ai_dock.raise_()

    def _menus(self):
        mb = self.menuBar()

        def act(menu, text, slot, key=None):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        f = mb.addMenu("&Файл")
        act(f, "Новый проект", self.new_project, QKeySequence.New)
        act(f, "Открыть…", self.open_project, QKeySequence.Open)
        act(f, "Сохранить", self.save_project, QKeySequence.Save)
        act(f, "Сохранить как…", lambda: self.save_project(as_new=True), "Ctrl+Shift+S")
        f.addSeparator()
        act(f, "Экспорт листа в DXF…", self.export_dxf)
        act(f, "Экспорт листа в SVG…", self.export_svg)
        act(f, "Экспорт модели в STL…", lambda: self.export_mesh("stl"))
        act(f, "Экспорт модели в OBJ…", lambda: self.export_mesh("obj"))
        f.addSeparator()
        act(f, "Выход", self.close, "Alt+F4")
        e = mb.addMenu("&Правка")
        act(e, "Отменить", self.undo, QKeySequence.Undo)
        act(e, "Повторить", self.redo, "Ctrl+Y")
        act(e, "Удалить выделенное", self.delete_selected, QKeySequence.Delete)
        act(e, "Замкнуть контуры", self.close_contours)
        e.addSeparator()
        # сочетания работают в окне чертежа (не мешают Ctrl+C в чате) — здесь только подписи
        act(e, "Выделить всё\tCtrl+A", lambda: self.cur2d().select_all())
        act(e, "Копировать\tCtrl+C", self.copy_selection)
        act(e, "Вставить\tCtrl+V", self.paste)
        v = mb.addMenu("&Вид")
        act(v, "Показать всё", self._fit, "F")
        act(v, "3D: изометрия", lambda: self._view3d("iso"), "Ctrl+0")
        act(v, "3D: перспектива / ортогональная", lambda: (self.work.setCurrentIndex(2), self.view3d.toggle_projection()))
        act(v, "3D: центрировать модель", lambda: (self.work.setCurrentIndex(2), self.view3d.home()))
        v.addSeparator()
        cm = v.addMenu("Формат полотна")
        self.canvas_actions = {}
        group = QActionGroup(self)
        for k, (label, _, _) in CANVAS_MODES.items():
            a = cm.addAction(label)
            a.setCheckable(True)
            group.addAction(a)
            a.triggered.connect(lambda _=False, k=k: self.set_canvas(k))
            self.canvas_actions[k] = a
        act(v, "Вписать лист в окно", self.fit_sheet, "Ctrl+Shift+F")
        v.addSeparator()
        act(v, "Оформление…", self.show_appearance, "Ctrl+Shift+T")
        lib = mb.addMenu("&Библиотека")
        act(lib, "Каталог элементов и шаблонов", self.show_library, "Ctrl+B")
        tm = lib.addMenu("Шаблоны листов")
        for sec, title in library.SECTIONS.items():
            tpls = [t for t in library.TEMPLATES.values() if t.section == sec]
            if tpls:
                sm = tm.addMenu(title)
                for t in tpls:
                    act(sm, t.name, lambda _=False, tid=t.id: self.open_template(tid))
        em = lib.addMenu("Элементы и УГО")
        for sec, title in library.SECTIONS.items():
            blocks = [b for b in library.BLOCKS.values() if b.section == sec]
            if blocks:
                sm = em.addMenu(title)
                for group in dict.fromkeys(b.group for b in blocks):
                    gm = sm.addMenu(group)
                    for b in blocks:
                        if b.group == group:
                            act(gm, b.name, lambda _=False, bid=b.id: self.insert_block(bid))
        self.user_menu = lib.addMenu("Мои элементы")
        self.user_menu.aboutToShow.connect(self._fill_user_menu)
        lib.addSeparator()
        act(lib, "Сохранить выделенное в библиотеку…", self.save_to_library)
        m = mb.addMenu("&ИИ")
        act(m, "Настройки ИИ…", self.ai_settings)
        self.ai_action = act(m, "ИИ-помощник", self.show_ai, "Ctrl+I")
        act(m, "Очистить переписку", self._clear_chat)
        h = mb.addMenu("&Справка")
        act(h, "О программе", self.show_about)

    def _status(self):
        self.hint = QLabel("")
        self.coord = QLabel("")
        self.coord.setMinimumWidth(300)
        self.body_info = QLabel("")
        self.statusBar().addWidget(self.hint, 1)
        self.statusBar().addPermanentWidget(self.body_info)
        self.statusBar().addPermanentWidget(self.coord)

    # ================================================================ состояние
    def cur2d(self) -> SketchView:
        return self.sheet if self.work.currentIndex() == 1 else self.sketch

    def _on_tab(self, i):
        self._sync_theme()
        if i == 2:
            return
        v = self.cur2d()
        self.tool_panel.bind(v, v.tool)
        self.lower.setCurrentIndex(0 if v.tool == "select" else 1)
        self._sync_tool_buttons(v.tool)

    def refresh(self, sketch=True, fit3d=False):
        self._sync_canvas_ui()
        if self.edit_fid:
            f = self.project.feature(self.edit_fid)
            if f is None:
                self.edit_fid = None
            self.sketch.target_override = f["sketch"] if f else None
        else:
            self.sketch.target_override = None
        self.banner.setVisible(bool(self.edit_fid))
        if self.edit_fid:
            self.banner_label.setText(f"Редактируется эскиз операции «{self.project.feature(self.edit_fid)['name']}» — модель перестраивается при каждой правке")
        for v in (self.sketch, self.sheet):
            v.project = self.project
            v.selected = [i for i in v.selected if self.project.find(i)]
            if sketch or v is not self.cur2d():
                v.rebuild()
        QApplication.setOverrideCursor(Qt.WaitCursor) if any(f["type"] in ("fillet3d", "chamfer3d", "shell") for f in self.project.features) else None
        try:
            self.solid = geo.build_solid(self.project.features)
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        self.view3d.show_solid(self.solid, fit=fit3d)
        self._sync_manip()
        self._update_views()
        self._fill_tree()
        self._fill_props()
        if self.ctx_editor is not None and self.ctx_editor.isVisible():
            self.ctx_editor.refresh()   # ПКМ-панель показывает уже изменённые значения
        c = geo.contours(self.project.profile_of(self.sketch.target()))
        lo, hi = self.solid.bbox()
        body = "нет тела" if self.solid.empty else f"тело {hi[0]-lo[0]:.1f}×{hi[1]-lo[1]:.1f}×{hi[2]-lo[2]:.1f} мм, {self.solid.volume / 1000:.2f} см³"
        self.body_info.setText(f"контуров в эскизе: {c.closed}" + (f", незамкнутых: {c.open_chains}" if c.open_chains else "") + f"  ·  {body}")
        self._title()

    def _sketch_edited(self):
        self.dirty = True
        self.refresh(sketch=False)

    def _title(self):
        name = os.path.basename(self.path) if self.path else "новый проект"
        self.setWindowTitle(f"{self.project.name} — {name}{' *' if self.dirty else ''} — {APP}")

    def _item(self, parent, text, kind, key=None, tip=None, red=False):
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole, (kind, key))
        if tip:
            it.setToolTip(0, tip)
        if red:
            it.setForeground(0, QColor(self._tone("#c22f2f")))
        (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
        return it

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        sel = set(self.cur2d().selected)
        root = self._item(None, f"⬢  {self.project.name}", "project")
        self._item(root, "▭  Плоскость XY", "plane", "XY")
        sk = self._item(root, f"✎  Текущий эскиз ({len(self.project.entities)})", "sketch")
        self._entity_items(sk, self.project.entities, sel)
        for f in self.project.features:
            err = self.solid.statuses.get(f["id"])
            text = f"{FEATURE_GLYPH.get(f['type'], '⬆') if f.get('op') != 'cut' else '⬇'}  {f['name']}" + ("  ⚠" if err else "") + ("  (подавлено)" if f.get("suppressed") else "")
            it = self._item(root, text, "feature", f["id"], err or "Двойной щелчок — точное значение; «Параметры операции…» — все поля", bool(err))
            it.setSelected(f["id"] == self.sel_feature)
            if f.get("sketch"):
                fs = self._item(it, f"✎  Эскиз ({len(f['sketch'])})" + ("  — редактируется" if f["id"] == self.edit_fid else ""), "fsketch", f["id"], "Двойной щелчок — редактировать эскиз")
                if f["id"] == self.edit_fid:
                    for e in f["sketch"]:
                        self._item(fs, entity_label(e), "entity", e["id"]).setSelected(e["id"] in sel)
                    fs.setExpanded(True)
                it.setExpanded(f["id"] == self.edit_fid)
        dr = self._item(root, f"▤  Чертёж ({len(self.project.drawing)})", "drawing")
        if self.project.sheet():
            fr = self.project.frame
            self._item(dr, f"⊡  {fr['format']} {'альбомный' if fr['orient'] == 'landscape' else 'книжный'}, М {fr['scale']}", "frame", None, "Двойной щелчок — основная надпись")
        else:
            self._item(dr, "∞  Бесконечное полотно (фрагмент)", "canvas", None, "Формат полотна — на ленте «Чертёж» или в меню «Вид»")
        self._entity_items(dr, [e for e in self.project.drawing if e.get("gen") != "views"], sel)
        root.setExpanded(True)
        sk.setExpanded(len(self.project.entities) <= 40)
        self.tree.blockSignals(False)

    def _entity_items(self, parent, ents, sel):
        """Примитивы — по одному; экземпляр элемента библиотеки — одним узлом «⊞ Имя  маркировка»."""
        seen = set()
        for e in ents:
            inst = e.get("blk")
            if not inst:
                self._item(parent, entity_label(e), "entity", e["id"]).setSelected(e["id"] in sel)
            elif inst not in seen:
                seen.add(inst)
                label = library.label_of(ents, inst)
                it = self._item(parent, f"⊞  {self._block_name(e)}" + (f"  {label}" if label else ""), "block", inst, "Двойной щелчок — маркировка")
                it.setSelected(e["id"] in sel)

    @staticmethod
    def _block_name(e) -> str:
        try:
            return library.get_block(e.get("blk_id", "")).name
        except ValueError:
            return "Элемент"

    def _block_ids(self, inst) -> list[str]:
        for lst in (self.project.drawing, self.sketch.target()):
            ids = [e["id"] for e in lst if e.get("blk") == inst]
            if ids:
                return ids
        return []

    def _clear_props(self):
        """Поля убираются через deleteLater: панель перестраивается и из обработчика самого поля (Enter в «Длина L»)."""
        self.prop_spins = {}
        while self.props_form.rowCount():
            row = self.props_form.takeRow(0)
            for item in (row.labelItem, row.fieldItem):
                w = item.widget() if item is not None else None
                if w is not None:
                    w.hide()
                    w.deleteLater()

    def _spin(self, value, on_done, lo=-1e5, hi=1e5, dec=2, key=None):
        """Поле числа: точность 0,01 мм, шаг 1 мм; значение применяется по Enter или при уходе из поля."""
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSingleStep(1.0)
        s.setValue(value)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(on_done)
        if key:
            self.prop_spins[key] = s
        return s

    def _geom_rows(self, e):
        """Панель параметров объекта по-кадровски: отрезок — L, α, начало, конец; окружность — Ø, R, центр, оси."""
        eid, t, form = e["id"], e["type"], self.props_form
        geo_ = lambda k: (lambda v: self._set_geom(eid, k, v))  # noqa: E731
        if t == "line":
            form.addRow("Длина L", self._spin(params.line_length(e), geo_("length"), 0.01, 1e5, key="length"))
            form.addRow("Угол α, °", self._spin(params.line_angle(e), geo_("angle"), -360, 360, key="angle"))
            for k, lab in (("x1", "Начало X1"), ("y1", "Начало Y1"), ("x2", "Конец X2"), ("y2", "Конец Y2")):
                form.addRow(lab, self._spin(e[k], geo_(k), key=k))
        elif t in ("circle", "arc"):
            rows = [("d", "Диаметр Ø", 2 * e["r"]), ("r", "Радиус R", e["r"])]
            for k, lab, val in (rows if t == "circle" else rows[::-1]):
                form.addRow(lab, self._spin(val, geo_(k), 0.01, 2e5, key=k))
            form.addRow("Центр X", self._spin(e["cx"], geo_("cx"), key="cx"))
            form.addRow("Центр Y", self._spin(e["cy"], geo_("cy"), key="cy"))
            if t == "arc":
                form.addRow("Угол начала, °", self._spin(e["a0"], geo_("a0"), -360, 360, key="a0"))
                form.addRow("Угол конца, °", self._spin(e["a1"], geo_("a1"), -360, 360, key="a1"))
        style = QComboBox()
        for k in STYLES:
            style.addItem(STYLE_LABEL[k], k)
        style.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        style.setMinimumContentsLength(10)   # подпись «Стиль линии» не обрезается
        style.setCurrentIndex(STYLES.index(e["style"]))
        style.currentIndexChanged.connect(lambda i: self._set_field(eid, "style", STYLES[i]))
        form.addRow("Стиль линии", style)
        if t == "circle":
            ax = QCheckBox("Осевые линии")
            ax.setChecked(bool(e.get("axes")))
            ax.toggled.connect(lambda on: self._set_field(eid, "axes", on))
            self.prop_checks = {"axes": ax}
            form.addRow("", ax)

    def _set_geom(self, eid, key, value):
        """Число из панели или быстрого ввода — через params.set_param: длина от начала по углу, Ø ↔ R и т.д."""
        e = self.project.find(eid)
        if e is None:
            return
        cur = {"length": params.line_length, "angle": params.line_angle}.get(key)
        now = cur(e) if cur and e["type"] == "line" else 2 * e["r"] if key == "d" else e.get(key)
        if isinstance(now, (int, float)) and abs(now - value) < 1e-9:
            return
        self._edit(lambda: params.set_param(e, key, value))

    def _rect_of(self, eid):
        lst = self.project.container_of(eid)
        return params.rect_lines(lst, eid) if lst is not None else None

    def _set_rect(self, eid, key, value):
        lines = self._rect_of(eid)
        if lines and abs(dict(zip("xywh", params.rect_info(lines)))[key] - value) > 1e-9:
            self._edit(lambda: params.set_rect_param(lines, key, value))

    def _set_dim_value(self, eid, value):
        d = self.project.find(eid)
        if d is not None and abs(params.dim_value(d) - value) > 1e-9:
            self._edit(lambda: params.drive_dim(self.project, d, value))

    def _fill_props(self, kind=None, key=None):
        self._clear_props()
        if kind is None and self.sel_feature and self.work.currentIndex() == 2 and self.project.feature(self.sel_feature):
            kind, key = "feature", self.sel_feature       # в 3D панель показывает операцию, выбранную на модели
        if kind is None:
            sel = self.cur2d().selected
            insts = {(self.project.find(i) or {}).get("blk") for i in sel}
            one_block = bool(sel) and len(insts) == 1 and None not in insts
            lines = self._rect_of(sel[0]) if len(sel) == 4 else None
            if lines and {e["id"] for e in lines} == set(sel):
                kind, key = "rect", sel[0]
            else:
                kind, key = ("entity", sel[0]) if len(sel) == 1 or one_block else ("group", None) if sel else ("project", None)
        if kind == "group":   # несколько объектов: сводка и общие параметры
            self.prop_rows = Rows(self.props_form)
            self._build_editor(self.prop_rows, self.cur2d(), popup=False)
            self.prop_spins.update({k: w for k, w in self.prop_rows.fields.items() if isinstance(w, QDoubleSpinBox)})
            return
        if kind == "rect":
            lines = self._rect_of(key)
            if lines:
                x, y, w, h = params.rect_info(lines)
                self.props_form.addRow(QLabel("<b>Прямоугольник</b>"))
                for k, lab, val, lo in (("w", "Ширина W", w, 0.01), ("h", "Высота H", h, 0.01), ("x", "Угол X", x, -1e5), ("y", "Угол Y", y, -1e5)):
                    self.props_form.addRow(lab, self._spin(val, lambda v, k=k: self._set_rect(key, k, v), lo, 1e5, key=k))
                style = QComboBox()
                for k in STYLES:
                    style.addItem(STYLE_LABEL[k], k)
                style.setCurrentIndex(STYLES.index(lines[0]["style"]))
                style.currentIndexChanged.connect(lambda i: self._edit(lambda: [ln.__setitem__("style", STYLES[i]) for ln in self._rect_of(key)]))
                self.props_form.addRow("Стиль линии", style)
            return
        if kind == "entity" and (self.project.find(key) or {}).get("blk"):
            e = self.project.find(key)
            lst = self.project.container_of(key)
            self.props_form.addRow(QLabel(f"<b>⊞ {html.escape(self._block_name(e))}</b>"))
            le = QLineEdit(library.label_of(lst, e["blk"]))
            le.editingFinished.connect(lambda w=le, inst=e["blk"], lst=lst: self._set_block_label(lst, inst, w.text()))
            self.props_form.addRow("Маркировка", le)
            self.props_form.addRow(QLabel(f"Примитивов: {sum(1 for x in lst if x.get('blk') == e['blk'])}"))
            return
        if kind == "entity":
            e = self.project.find(key)
            if not e:
                return
            self.props_form.addRow(QLabel(f"<b>{html.escape(entity_label(e))}</b>"))
            if e["type"] in ("line", "circle", "arc"):
                self._geom_rows(e)
            else:
                for field in ops.NUMERIC.get(e["type"], ()):
                    lo = 1e-3 if field in ("r", "step", "h") else -1e5
                    self.props_form.addRow(FIELD_NAMES.get(field, field), self._spin(e[field], lambda v, f=field, eid=key: self._set_field(eid, f, v), lo=lo, dec=3, key=field))
            if e["type"] in ("dim", "diadim", "raddim") and params.associative(e):
                lab = QLabel("Управляющий размер: новое значение меняет геометрию")
                lab.setObjectName("hint")
                lab.setWordWrap(True)
                self.props_form.insertRow(1, "Значение", self._spin(params.dim_value(e), lambda v: self._set_dim_value(key, v), 0.01, 1e6, key="value"))
                self.props_form.insertRow(2, lab)
            if e["type"] in ("dim", "diadim", "raddim", "angdim"):
                b = QPushButton("Допуск и текст…")
                b.clicked.connect(lambda: self.edit_dim_form(key))
                self.props_form.addRow(b)
        elif kind == "feature":
            f = self.project.feature(key)
            if not f:
                return
            self.props_form.addRow(QLabel(f"<b>{f['name']}</b>"))
            if f["type"] == "extrude" and f.get("op") == "cut":
                th = QCheckBox("через всё")
                th.setChecked(bool(f.get("through")))
                th.toggled.connect(lambda on: self._set_feature(key, "through", on))
                self.props_form.addRow("Вырез", th)
            spec = ops.feature_value(f)
            if spec:
                param, label, value, lo, hi = spec
                self.props_form.addRow(label, self._spin(value, lambda v, p=param: self._set_feature_value(key, p, v), lo, hi, key=param))
            if any(h["fid"] == key for h in self.solid.handles):
                tip = QLabel("В 3D: щёлкните грань и тяните стрелку — размер меняется мышью; двойной щелчок по размеру — точное значение")
                tip.setObjectName("hint")
                tip.setWordWrap(True)
                self.props_form.addRow(tip)
            b = QPushButton("Параметры операции…")
            b.clicked.connect(lambda: self.edit_feature(key))
            self.props_form.addRow(b)
            if f.get("sketch"):
                b2 = QPushButton("Редактировать эскиз")
                b2.clicked.connect(lambda: self.edit_feature_sketch(key))
                self.props_form.addRow(b2)
            sup = QCheckBox("подавить")
            sup.setChecked(bool(f.get("suppressed")))
            sup.toggled.connect(lambda on: self._set_feature(key, "suppressed", on))
            self.props_form.addRow("", sup)
            err = self.solid.statuses.get(key)
            if err:
                lab = QLabel(f"⚠ {html.escape(err)}")
                lab.setWordWrap(True)
                lab.setStyleSheet(f"color:{self._tone('#c22f2f')}")
                self.props_form.addRow(lab)
            rm = QPushButton("Удалить операцию")
            rm.clicked.connect(lambda: self._remove_feature(key))
            self.props_form.addRow(rm)
        else:
            for label, attr in (("Наименование", "name"), ("Обозначение", "designation"), ("Материал", "material")):
                le = QLineEdit(getattr(self.project, attr))
                le.editingFinished.connect(lambda a=attr, w=le: self._set_prop(a, w.text()))
                self.props_form.addRow(label, le)
            c = geo.contours(self.project.profile_entities())
            info = QLabel(f"Объектов эскиза: {len(self.project.entities)}\nЗамкнутых контуров: {c.closed}\nНезамкнутых цепочек: {c.open_chains}\n"
                          f"Операций: {len(self.project.features)}\nОбъектов на листе: {len(self.project.drawing)}")
            self.props_form.addRow(info)

    # ================================================================ правки
    def _edit(self, fn, sketch=True) -> bool:
        self.history.push()
        try:
            fn()
        except ValueError as exc:
            self.history.undo_stack.pop()
            warn(self, APP, str(exc))
            return False
        params.sync_dims(self.project)   # размеры — за геометрией, текст размера обновляется сам
        self.dirty = True
        self.refresh(sketch=sketch)
        return True

    def _set_field(self, eid, field, value):
        e = self.project.find(eid)
        if e and e.get(field) != value:
            self._edit(lambda: e.__setitem__(field, value))

    def _set_feature(self, fid, field, value):
        f = self.project.feature(fid)
        if f:
            self._edit(lambda: f.__setitem__(field, value), sketch=False)

    def _set_feature_value(self, fid, param, value) -> bool:
        """Главное число операции (высота, глубина, угол…): одна правка в истории, модель и виды на листе — заново."""
        f = self.project.feature(fid)
        if f is None or (abs(float(f.get(param, 0)) - float(value)) < 1e-9 and not (param == "depth" and f.get("through"))):
            return False

        def fn():
            f[param] = float(value)
            if param == "depth":
                f["through"] = False
        return self._edit(fn, sketch=False)

    def quick_edit_feature(self, fid):
        """Быстрый ввод главного числа операции у курсора (двойной щелчок по операции или по размеру в 3D)."""
        f = self.project.feature(fid) if fid else None
        if f is None:
            return
        spec = ops.feature_value(f)
        if spec is None:          # вырез «через всё», операции без числа — полная форма
            self.edit_feature(fid)
            return
        param, label, value, lo, hi = spec
        v = quick_edit(self, f["name"], [(param, label, value, lo, hi)])
        if v is not None and abs(v[param] - value) > 1e-9:
            self._set_feature_value(fid, param, v[param])

    # ---------------------------------------------------------------- прямое редактирование в 3D
    def _select_feature(self, fid, anchor=None):
        """Выбрать операцию (щелчком по грани или в дереве): ручка на грани, строка в дереве, поля в «Параметрах»."""
        self.sel_feature = fid
        self._manip_anchor = None if anchor is None else (float(anchor[0]), float(anchor[1]))
        self._sync_manip()
        self.tree.blockSignals(True)
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            on = fid is not None and it.data(0, Qt.UserRole) == ("feature", fid)
            it.setSelected(on)
            if on:
                self.tree.setCurrentItem(it)
            stack += [it.child(i) for i in range(it.childCount())]
        self.tree.blockSignals(False)
        self._fill_props("feature", fid) if fid else self._fill_props()

    def _sync_manip(self):
        """После каждой перестройки — ручка выбранной операции на её грани; грани нет (перекрыта, ошибка) — ручки нет."""
        m = self.view3d.manip
        if m.dragging:
            return
        fid = self.sel_feature
        if fid and self.project.feature(fid) is None:
            self.sel_feature = fid = None
        h = next((h for h in self.solid.handles if h["fid"] == fid), None) if fid else None
        tris = geo.face_triangles(self.solid, self.project.features, h) if h else []
        if h is None or not len(tris):
            m.detach()
            return
        c = self.solid.verts[self.solid.faces[tris]].mean(axis=1)
        a = self._manip_anchor
        if a is None or not geo.points_in_polygons(a[0], a[1], geo.feature_polygons(self.project.feature(fid)))[0]:
            ref = c[:, :2].mean(axis=0) if a is None else np.array(a)
            a = tuple(c[int(np.argmin(np.linalg.norm(c[:, :2] - ref, axis=1))), :2])   # точка на самой грани
            self._manip_anchor = (float(a[0]), float(a[1]))
        m.attach(h, self.solid, tris, a)

    def _on_face_clicked(self, hit):
        if self.view3d.manip.dragging:
            return
        h = geo.handle_at(self.solid, self.project.features, hit["point"], hit["normal"]) if hit else None
        if h is None:
            self._select_feature(None)
            if hit is not None:
                self.hint.setText("Эта грань задаётся эскизом операции — двойной щелчок по операции в дереве: точное число, "
                                  "«Редактировать эскиз» — форма. Стрелка появляется на верхней грани выдавливания и на дне выреза")
            return
        self._select_feature(h["fid"], hit["point"])
        label = {"height": "высота H", "depth": "глубина выреза"}[h["param"]]
        self.hint.setText(f"{h['name']}: тяните стрелку — {label} (шаг 1 мм, с Shift — 0,1 мм); двойной щелчок по размеру — "
                          "точное значение; Esc — снять выбор")

    def _on_face_double(self, hit):
        h = geo.handle_at(self.solid, self.project.features, hit["point"], hit["normal"]) if hit else None
        if h is not None:
            self._select_feature(h["fid"], hit["point"])
            self.quick_edit_feature(h["fid"])

    def _on_handle_moved(self, value: float):
        """Тянут стрелку: поле в «Параметрах» и плашка — новое число, фантом — будущая форма тела."""
        m = self.view3d.manip
        h = m.handle
        f = self.project.feature(h["fid"]) if h else None
        if f is None:
            return
        spin = self.prop_spins.get(h["param"])
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        feats = geo.with_handle_value(self.project.features, h, value)
        after = feats[next(i for i, x in enumerate(feats) if x["id"] == h["fid"]):]
        slow = self._ghost_slow or any(x["type"] in geo.SLOW_FEATURES and not x.get("suppressed") for x in after)
        t0 = time.perf_counter()
        try:
            ghost = geo.handle_tool(feats, h, value) if slow else geo.build_solid(feats)
        except Exception:  # noqa: BLE001 — фантом не построился: стрелка и число всё равно следуют за мышью
            ghost = None
        if not slow and time.perf_counter() - t0 > 0.15:
            self._ghost_slow = True               # тяжёлое дерево: дальше фантом — только тело операции
        if ghost is not None and not ghost.empty:
            self.view3d.show_ghost(ghost)
            lo, hi = ghost.bbox()
            size = f" · габарит {hi[0] - lo[0]:.1f}×{hi[1] - lo[1]:.1f}×{hi[2] - lo[2]:.1f} мм" if not slow else ""
        else:
            size = ""
        self.hint.setText(f"{f['name']}: {m.text(value)}{size} — отпустите, чтобы применить; Esc или ПКМ — отмена")

    def _on_handle_released(self, value: float):
        self._ghost_slow = False
        h = self.view3d.manip.handle
        if h is None:
            return
        name = (self.project.feature(h["fid"]) or {}).get("name", "")
        if self._set_feature_value(h["fid"], h["param"], value):
            self.hint.setText(f"{name}: {self.view3d.manip.text(value)} — модель и чертёж перестроены (Ctrl+Z — отменить)")
        else:
            self._sync_manip()

    def _on_handle_cancelled(self):
        self._ghost_slow = False
        h = self.view3d.manip.handle
        spin = self.prop_spins.get(h["param"]) if h else None
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(h["value"])
            spin.blockSignals(False)
        self.hint.setText("Перетаскивание отменено")

    def _remove_feature(self, fid):
        if self.edit_fid == fid:
            self.edit_fid = None
        self._edit(lambda: setattr(self.project, "features", [f for f in self.project.features if f["id"] != fid]), sketch=False)

    def _set_prop(self, attr, value):
        if getattr(self.project, attr) != value:
            self._edit(lambda: setattr(self.project, attr, value))

    def _on_tree_selection(self):
        items = self.tree.selectedItems()
        if not items:
            return
        kind, key = items[0].data(0, Qt.UserRole)
        if (key if kind == "feature" else None) != self.sel_feature:   # ручка в 3D — у выбранной операции
            self.sel_feature, self._manip_anchor = (key if kind == "feature" else None), None
            self._sync_manip()
        if kind in ("entity", "block"):
            ids = []
            for it in items:
                k, v = it.data(0, Qt.UserRole)
                ids += [v] if k == "entity" else self._block_ids(v) if k == "block" else []
            if not ids:
                return
            if kind == "block":
                kind, key = "entity", ids[0]
            in_drawing = any(e["id"] == ids[0] for e in self.project.drawing)
            self.work.setCurrentIndex(1 if in_drawing else 0)
            self.cur2d().selected = ids
            self.cur2d().rebuild()
        self._fill_props(kind, key)

    def _on_tree_double(self, item, _col):
        kind, key = item.data(0, Qt.UserRole)
        if kind == "block":
            ids = self._block_ids(key)
            if ids:
                self.edit_entity(ids[0])
        elif kind == "feature":
            self.quick_edit_feature(key)
        elif kind == "fsketch":
            self.edit_feature_sketch(key)
        elif kind == "entity":
            self.edit_entity(key)
        elif kind == "frame":
            self.edit_stamp("name")
        elif kind == "sketch":
            self.finish_sketch_edit()
            self.work.setCurrentIndex(0)

    def _on_sketch_selection(self, ids):
        self._fill_tree()
        self._fill_props()

    def set_tool(self, name):
        if name == "frame" and not self.project.sheet():
            self.set_canvas(self.cfg.get("last_sheet", "A3L"))
        v = self.cur2d()
        if self.work.currentIndex() == 2 or (name == "frame" and v is not self.sheet):
            self.work.setCurrentIndex(1 if name == "frame" else 0)
            v = self.cur2d()
        v.set_tool(name)
        self.tool_panel.bind(v, name)
        self.lower.setCurrentIndex(0 if name == "select" else 1)
        self._sync_tool_buttons(name)
        v.setFocus()

    def _sync_tool_buttons(self, name):
        for k, b in self.tool_buttons.items():
            b.setChecked(k == name)
        self.lower.setCurrentIndex(0 if name == "select" else 1)

    def _set_style(self, i):
        for v in (self.sketch, self.sheet):
            v.style = STYLES[i]
        sel = self.cur2d().selected
        if sel:  # стиль применяется и к выделенным кривым
            def fn():
                for eid in sel:
                    e = self.project.find(eid)
                    if e and e["type"] in ("line", "circle", "arc"):
                        e["style"] = STYLES[i]
            self._edit(fn)

    def _set_snaps(self):
        on = {k for k, a in self.snap_actions.items() if a.isChecked()}
        for v in (self.sketch, self.sheet):
            v.snaps = on

    def delete_selected(self):
        if self.chat_input.hasFocus():
            return
        ids = list(self.cur2d().selected)
        if ids:
            self.cur2d().selected = []
            self._edit(lambda: self.project.remove(ids))
            return
        items = self.tree.selectedItems()
        if items and items[0].data(0, Qt.UserRole)[0] == "feature":
            self._remove_feature(items[0].data(0, Qt.UserRole)[1])

    def close_contours(self):
        ents = self.cur2d().target()
        self.history.push()
        n = geo.fix_gaps(ents, 1.0)
        if not n:
            self.history.undo_stack.pop()
            self.hint.setText("Разрывов до 1 мм между концами отрезков не найдено")
            return
        self.dirty = True
        self.refresh()
        self.hint.setText(f"Сведено стыков: {n}")

    # ================================================================ 3D
    def _feature(self, kind, **params):
        if self.edit_fid:
            warn(self, APP, "Сначала закончите редактирование эскиза операции")
            return None
        self.history.push()
        try:
            f = ops.create_feature(self.project, kind, **params)
        except ValueError as exc:
            self.history.undo_stack.pop()
            warn(self, FEATURE_LABEL.get(kind, "Операция"), str(exc))
            return None
        self.dirty = True
        self.refresh(fit3d=self.solid.empty)
        self.work.setCurrentIndex(2)
        err = self.solid.statuses.get(f["id"])
        self.hint.setText(f"{f['name']}: {err}" if err else f"{f['name']} построено. Эскиз ушёл в операцию — двойной щелчок по нему в дереве открывает правку")
        return f

    def extrude(self):
        v = ask_form(self, "Выдавливание", [("height", "Высота, мм", "float", 10.0, (0.001, 1e5)),
                                             ("base", "Начало", "choice", "plane", [("plane", "от плоскости XY"), ("top", "от верха тела")]),
                                             ("op", "Операция", "choice", "add", OPS)],
                     "Вложенные контуры — отверстия: внешний квадрат минус внутренние окружности.")
        if v:
            self._feature("extrude", **v)

    def cut(self):
        v = ask_form(self, "Вырезать выдавливанием", [("through", "Через всё", "bool", True), ("depth", "Глубина от верха, мм", "float", 5.0, (0.001, 1e5))])
        if v:
            self._feature("cut", **({"through": True} if v["through"] else {"depth": v["depth"]}))

    def revolve(self):
        v = ask_form(self, "Элемент вращения", [("angle", "Угол, °", "float", 360.0, (0.1, 360)), ("op", "Операция", "choice", "add", OPS)],
                     "Профиль вращается вокруг первой осевой линии эскиза. Профиль не должен пересекать ось.")
        if v:
            self._feature("revolve", **v)

    def shell(self):
        v = ask_form(self, "Оболочка", [("thickness", "Толщина стенки, мм", "float", 2.0, (0.01, 1e4)), ("open_top", "Открыть верхнюю грань", "bool", True)])
        if v:
            self._feature("shell", **v)

    def edge3d(self, kind):
        v = ask_form(self, FEATURE_LABEL[kind], [("size", "Радиус, мм" if kind == "fillet3d" else "Катет, мм", "float", 2.0, (0.01, 1e4))],
                     "Обрабатываются все внешние (выпуклые) рёбра тела. Для отдельных вертикальных рёбер используйте "
                     "«Скругление» или «Фаску» в эскизе до выдавливания.")
        if v:
            self._feature(kind, **v)

    def edit_feature(self, fid):
        f = self.project.feature(fid)
        if f is None:
            return
        fields, t = [], f["type"]
        if t == "extrude" and f.get("op") == "cut":
            fields = [("through", "Через всё", "bool", f.get("through", True)), ("depth", "Глубина, мм", "float", f.get("depth", 5), (0.001, 1e5))]
        elif t == "extrude":
            fields = [("height", "Высота, мм", "float", f["height"], (0.001, 1e5)),
                      ("base", "Начало", "choice", f.get("base", "plane"), [("plane", "от плоскости XY"), ("top", "от верха тела")]),
                      ("op", "Операция", "choice", f.get("op", "add"), OPS)]
        elif t == "revolve":
            fields = [("angle", "Угол, °", "float", f["angle"], (0.1, 360)), ("op", "Операция", "choice", f.get("op", "add"), OPS)]
        elif t == "shell":
            fields = [("thickness", "Толщина стенки, мм", "float", f["thickness"], (0.01, 1e4)), ("open_top", "Открыть верх", "bool", f.get("open_top", True))]
        else:
            fields = [("size", "Размер, мм", "float", f["size"], (0.01, 1e4))]
        v = ask_form(self, f["name"], fields, "Модель перестроится сразу после «ОК».")
        if v:
            self._edit(lambda: f.update(v), sketch=False)
            self.work.setCurrentIndex(2)

    def edit_feature_sketch(self, fid):
        f = self.project.feature(fid)
        if not f or not f.get("sketch"):
            return
        self.edit_fid = fid
        self.cur2d().cancel()
        self.work.setCurrentIndex(0)
        self.refresh()
        self.sketch.fit_all()
        self.hint.setText("Правьте эскиз: каждая правка сразу перестраивает 3D-модель")

    def finish_sketch_edit(self):
        if self.edit_fid:
            self.edit_fid = None
            self.sketch.selected = []
            self.refresh()

    def drawing_from_model(self):
        if self.solid.empty:
            warn(self, "Чертёж по модели", "Нет тела: сначала постройте модель")
            return
        info = {}

        def fn():
            info.update(make_drawing(self.project, self.solid))
            self._views_sig = self._solid_sig()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = self._edit(fn)
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            self.work.setCurrentIndex(1)
            self.sheet.fit_all()
            self.hint.setText(f"Виды построены: масштаб {info['scale']}, линий {info['lines']}. Невидимые линии — штриховые")

    def _solid_sig(self):
        if self.solid.empty:
            return None
        lo, hi = self.solid.bbox()
        return (round(self.solid.volume, 4), *(round(float(v), 4) for v in (*lo, *hi)))

    def _update_views(self):
        """Виды «Чертежа по модели» ассоциативны, как в КОМПАС: модель изменилась — виды и габариты перестраиваются."""
        if self.solid.empty or not any(e.get("gen") == "views" for e in self.project.drawing):
            self._views_sig = None
            return
        sig = self._solid_sig()
        if getattr(self, "_views_sig", None) is None:   # открыли проект с видами: считаем их актуальными
            self._views_sig = sig
            return
        if sig != self._views_sig:
            info = make_drawing(self.project, self.solid)
            self._views_sig = sig
            for v in (self.sketch, self.sheet):
                v.rebuild()
            self.hint.setText(f"Модель изменилась — виды на листе перестроены (М {info['scale']})")

    # ================================================================ оформление
    def edit_entity(self, eid):
        """Двойной щелчок по объекту: быстрый ввод у курсора (длина отрезка, Ø окружности, значение размера)."""
        e = self.project.find(eid)
        if e is None:
            return
        t = e["type"]
        if not e.get("blk") and t in ("line", "circle", "arc", "dim", "diadim", "raddim"):
            if self._quick_edit(e):
                return
        self.edit_dim_form(eid)

    def _quick_edit(self, e) -> bool:
        t, eid = e["type"], e["id"]
        lines = self._rect_of(eid) if t == "line" else None
        if lines:
            x, y, w, h = params.rect_info(lines)
            v = quick_edit(self, "Прямоугольник", [("w", "Ширина W", w, 0.01, 1e5), ("h", "Высота H", h, 0.01, 1e5)])
            if v and (abs(v["w"] - w) > 1e-9 or abs(v["h"] - h) > 1e-9):
                self._edit(lambda: params.set_rect(lines, x, y, v["w"], v["h"]))
        elif t == "line":
            L, a = params.line_length(e), params.line_angle(e)
            v = quick_edit(self, "Отрезок", [("length", "Длина L", L, 0.01, 1e5), ("angle", "Угол α, °", a, -360, 360)])
            if v and (abs(v["length"] - L) > 1e-9 or abs(v["angle"] - a) > 1e-9):
                def fn():
                    if abs(v["angle"] - a) > 1e-9:
                        params.set_param(e, "angle", v["angle"])
                    if abs(v["length"] - L) > 1e-9:
                        params.set_param(e, "length", v["length"])
                self._edit(fn)
        elif t in ("circle", "arc"):
            r = e["r"]
            fields = [("d", "Диаметр Ø", 2 * r, 0.01, 2e5), ("r", "Радиус R", r, 0.01, 1e5)]
            v = quick_edit(self, "Окружность" if t == "circle" else "Дуга", fields if t == "circle" else fields[::-1],
                           ("d", "r", 0.5))
            if v:   # изменённое поле главнее: введён Ø — радиус из него, введён R — из R
                new_r = v["d"] / 2 if abs(v["d"] - 2 * r) > 1e-9 else v["r"]
                if abs(new_r - r) > 1e-9:
                    self._edit(lambda: params.set_param(e, "r", new_r))
        elif params.associative(e):
            cur = params.dim_value(e)
            label = {"dim": "Размер", "diadim": "Размер Ø", "raddim": "Размер R"}[t]
            v = quick_edit(self, f"{label} (управляющий)", [("value", "Значение", cur, 0.01, 1e6)])
            if v and abs(v["value"] - cur) > 1e-9:
                self._edit(lambda: params.drive_dim(self.project, e, v["value"]))
        else:
            return False
        return True

    def edit_dim_form(self, eid):
        """Полная форма объекта: числа, тип линии, допуск и свой текст размера, текст надписи."""
        e = self.project.find(eid)
        if e is None:
            return
        if e.get("blk"):   # элемент библиотеки: правится маркировка всего экземпляра
            lst = self.project.container_of(eid)
            v = ask_form(self, self._block_name(e), [("label", "Маркировка", "text", library.label_of(lst, e["blk"]))],
                         "Позиционное обозначение привязано к элементу: QF1, ОП-12, марка оси…")
            if v is not None:
                self._set_block_label(lst, e["blk"], v["label"])
            return
        fields = [(k, FIELD_NAMES.get(k, k), "float", e[k], ((1e-3, 1e5) if k in ("r", "step") else (-1e5, 1e5))) for k in ops.NUMERIC.get(e["type"], ())]
        if e["type"] in ("line", "circle", "arc"):
            fields.append(("style", "Тип линии", "choice", e["style"], [(k, STYLE_LABEL[k]) for k in STYLES]))
        note = ""
        if e["type"] in ("dim", "diadim", "raddim", "angdim"):
            fields += [("tol", "Допуск / квалитет", "combo_text", e.get("tol", ""), ["", "H7", "H7/g6", "h9", "js6", "±0,1", "±0,05", "+0,2/-0,1"]),
                       ("text", "Свой текст (вместо значения)", "text", e.get("text", ""))]
            note = "Допуск: ±0,1 · +0,2/-0,1 · квалитет H7 · посадка H7/g6. Пустое поле — без допуска."
        if e["type"] == "leader":
            fields.append(("text", "Текст на полке", "text", e["text"]))
        if e["type"] == "text":
            fields = [("text", "Текст", "text", e["text"])] + fields + [
                ("align", "Выравнивание", "choice", e.get("align", "left"), [("left", "влево"), ("center", "по центру"), ("right", "вправо")])]
        if e["type"] == "rough":
            fields += [("param", "Параметр", "choice", e["param"], [("Ra", "Ra"), ("Rz", "Rz")]), ("value", "Значение, мкм", "text", e["value"])]
        if e["type"] == "hatch":
            fields.append(("pattern", "Материал", "choice", e["pattern"], list(HATCH_PATTERNS.items())))
        v = ask_form(self, entity_label(e), fields, note)
        if v is None:
            return

        def fn():
            if "tol" in v:
                v["tol"] = check_tolerance(v["tol"])
            if e["type"] in ("circle", "arc") and v.get("r", 1) <= 0:
                raise ValueError("радиус должен быть больше нуля")
            if e["type"] == "text" and v.get("h", 1) <= 0:
                raise ValueError("высота шрифта должна быть больше нуля")
            e.update(v)
        self._edit(fn)

    def edit_frame(self):
        fr = self.project.frame or {}
        v = ask_form(self, "Формат листа", [("format", "Формат", "choice", fr.get("format", "A3"), [(k, k) for k in FORMATS]),
                                            ("orient", "Ориентация", "choice", fr.get("orient", "landscape"), [("landscape", "альбомная"), ("portrait", "книжная")])],
                     "ГОСТ 2.301. Рамка: 20 мм слева под подшивку, 5 мм с остальных сторон. A4 — обычно книжная.")
        if v and self._edit(lambda: ops.set_frame(self.project, v["format"], v["orient"])):
            self._remember_canvas(self.project.canvas_mode())
            self.work.setCurrentIndex(1)
            self.sheet.fit_sheet()

    def edit_stamp(self, focus="name"):
        if not self.project.frame:
            self.project.frame = default_frame()   # данные штампа; на фрагменте он не виден, но сохраняется в .k3d
        fr = self.project.frame
        people = fr.get("people", {})
        fields = [("name", "Наименование", "text", self.project.name), ("designation", "Обозначение (шифр)", "text", self.project.designation),
                  ("material", "Материал", "text", self.project.material), ("mass", "Масса", "text", fr.get("mass", "")),
                  ("scale", "Масштаб", "combo_text", fr.get("scale", "1:1"), [lab for _, lab in SCALES]),
                  ("litera", "Литера", "text", fr.get("litera", "")), ("sheet", "Лист", "text", fr.get("sheet", "1")),
                  ("sheets", "Листов", "text", fr.get("sheets", "1")), ("org", "Организация", "text", fr.get("org", ""))]
        fields += [(f"people.{r}", r, "text", people.get(r, "")) for r in STAMP_ROLES]
        v = ask_form(self, "Основная надпись (ГОСТ 2.104, форма 1)", fields, focus=focus)
        if v is None:
            return

        def fn():
            for k in ("name", "designation", "material"):
                setattr(self.project, k, v[k])
            for k in ("mass", "scale", "litera", "sheet", "sheets", "org"):
                fr[k] = v[k]
            fr["people"] = {r: v[f"people.{r}"] for r in STAMP_ROLES}
        self._edit(fn)
        self.work.setCurrentIndex(1)
        if not self.project.sheet():
            self.hint.setText("Основная надпись сохранена. На бесконечном полотне она скрыта — видна на листах А4/А3")

    def undo(self):
        if self.history.undo():
            self.dirty = True
            self.refresh()

    def redo(self):
        if self.history.redo():
            self.dirty = True
            self.refresh()

    def _view3d(self, name):
        self.work.setCurrentIndex(2)
        self.view3d.set_view(name)

    def _fit(self):
        if self.work.currentIndex() < 2:
            self.cur2d().fit_all()
        elif not self.solid.empty:
            self.view3d.fit(self.solid)

    # ================================================================ файлы
    def _replace_project(self, project: Project, path: str | None):
        self.project = project
        self._views_sig = None
        self.history = History(project)
        self.edit_fid = None
        for v in (self.sketch, self.sheet):
            v.selected = []
        self.path, self.dirty = path, False
        self.refresh(fit3d=True)
        self.dirty = False
        self._title()
        self.sketch.fit_all()
        self.sheet.fit_sheet()

    def _confirm_discard(self) -> bool:
        if not self.dirty or Ask.AUTO:
            return True
        r = QMessageBox.question(self, APP, "Сохранить изменения в проекте?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_project()
        return r == QMessageBox.Discard

    def new_project(self):
        if not self._confirm_discard():
            return
        v = ask_form(self, "Новый документ", [("name", "Наименование", "text", "Деталь"),
                                              ("canvas", "Формат полотна", "choice", self.cfg.get("canvas", "fragment"),
                                               [(k, lab) for k, (lab, _, _) in CANVAS_MODES.items()])],
                     "Формат можно сменить в любой момент на ленте «Чертёж» — начерченное не теряется.")
        if v is None:
            return
        project = Project(name=v["name"] or "Деталь")
        ops.set_canvas(project, v["canvas"])
        self._remember_canvas(v["canvas"])
        self._replace_project(project, None)

    def open_project(self, path: str | None = None):
        if not path:
            if not self._confirm_discard():
                return
            path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", self._dir(), FILTER)
            if not path:
                return
        try:
            self._replace_project(Project.load(path), path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Открыть", f"Не удалось открыть файл:\n{exc}")

    def save_project(self, as_new=False, path: str | None = None) -> bool:
        path = path or self.path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", os.path.join(self._dir(), f"{self.project.name}.k3d"), FILTER)
            if not path:
                return False
            if not path.lower().endswith(".k3d"):
                path += ".k3d"
        try:
            self.project.save(path)
        except OSError as exc:
            QMessageBox.critical(self, "Сохранить", f"Не удалось сохранить:\n{exc}")
            return False
        self.path, self.dirty = path, False
        self._title()
        self.hint.setText(f"Сохранено: {path}")
        return True

    def _dir(self):
        return os.path.dirname(self.path) if self.path else os.path.join(os.path.expanduser("~"), "Documents")

    def _ask_path(self, title, ext, flt):
        if Ask.AUTO:
            return Ask.answers.get(f"path.{ext}")
        base = os.path.splitext(self.path)[0] if self.path else os.path.join(self._dir(), self.project.name)
        path, _ = QFileDialog.getSaveFileName(self, title, f"{base}.{ext}", flt)
        if path and not path.lower().endswith("." + ext):
            path += "." + ext
        return path

    def _export_entities(self, kind):
        """(объекты, с рамкой) или None, если отменили. Лист — если открыт он или на нём что-то есть; иначе эскиз.
        На листах А4/А3 спрашивает, выгружать ли рамку и штамп."""
        if self.work.currentIndex() == 0 or not (self.project.drawing or self.project.sheet()):
            return self.sketch.target(), False
        if not self.project.sheet():
            return self.project.drawing, False
        v = ask_form(self, f"Экспорт в {kind}", [("with_frame", "Экспортировать вместе с рамкой и штампом ГОСТ", "bool",
                                                  self.cfg.get("export_frame", True))])
        if v is None:
            return None
        if self.cfg.get("export_frame", True) != v["with_frame"]:
            self.cfg["export_frame"] = v["with_frame"]
            self._save_cfg("export_frame")
        return self.project.drawing, v["with_frame"]

    def export_dxf(self):
        what = self._export_entities("DXF")
        path = what and self._ask_path("Экспорт в DXF", "dxf", "DXF (*.dxf)")
        if path:
            ents, frame = what
            with open(path, "wb") as f:
                f.write(to_dxf(self.project, ents, frame))
            self.hint.setText(f"DXF сохранён{' с рамкой и штампом' if frame else ''}: {path}")

    def export_svg(self):
        what = self._export_entities("SVG")
        path = what and self._ask_path("Экспорт в SVG", "svg", "SVG (*.svg)")
        if path:
            ents, frame = what
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_svg(self.project, ents, None, frame))
            self.hint.setText(f"SVG сохранён{' с рамкой и штампом' if frame else ''}: {path}")

    # ================================================================ формат полотна
    def _init_canvas(self, project):
        try:
            ops.set_canvas(project, self.cfg.get("canvas", "fragment"))
        except ValueError:
            ops.set_canvas(project, "fragment")

    def _save_cfg(self, *keys) -> bool:
        """Записать в config.json только эти ключи из self.cfg — остальное в файле (тема, ключ ИИ) не трогаем."""
        try:
            ai.update_config({k: self.cfg[k] for k in keys if k in self.cfg})
            return True
        except OSError:
            self.hint.setText(f"Не удалось записать {ai.config_path()}")
            return False

    def _remember_canvas(self, mode):
        """Последний выбранный формат — в config.json: с ним открывается новый документ."""
        changed = self.cfg.get("canvas") != mode
        self.cfg["canvas"] = mode
        if mode != "fragment":
            changed |= self.cfg.get("last_sheet") != mode
            self.cfg["last_sheet"] = mode
        if changed:
            self._save_cfg("canvas", "last_sheet")

    def set_canvas(self, mode):
        """Переключение «на лету»: объекты чертежа не меняются, на листе появляются рамка и штамп."""
        if mode is None or mode == self.project.canvas_mode():
            self._sync_canvas_ui()
            return
        if self._edit(lambda: ops.set_canvas(self.project, mode)):
            self._remember_canvas(mode)
            self.work.setCurrentIndex(1)
            self._sync_theme()
            self.sheet.fit_sheet()
            msg = f"Полотно: {CANVAS_MODES[mode][0]}"
            b = self.sheet.sheet_bounds()
            if b is not None and self.project.drawing:
                x0, y0, x1, y1 = drawing_bounds(self.project, self.project.drawing, False)
                if x0 + 5 < b.left() or y0 + 5 < b.top() or x1 - 5 > b.right() or y1 - 5 > b.bottom():
                    msg += " — часть чертежа за пределами листа; «Чертёж по модели» перестроит виды под этот формат"
            self.hint.setText(msg)

    def fit_sheet(self):
        self.work.setCurrentIndex(1)
        self.sheet.fit_sheet()

    def _sync_canvas_ui(self):
        mode = self.project.canvas_mode()
        if hasattr(self, "canvas_box"):
            self.canvas_box.blockSignals(True)
            self.canvas_box.setCurrentIndex(max(0, self.canvas_box.findData(mode)))
            self.canvas_box.blockSignals(False)
        for k, a in getattr(self, "canvas_actions", {}).items():
            a.setChecked(k == mode)

    def export_mesh(self, kind):
        if self.solid.empty:
            warn(self, "Экспорт", "Нет тела: сначала постройте модель.")
            return
        path = self._ask_path(f"Экспорт в {kind.upper()}", kind, f"{kind.upper()} (*.{kind})")
        if path:
            (geo.export_stl if kind == "stl" else geo.export_obj)(path, self.solid, self.project.name)
            self.hint.setText(f"{kind.upper()} сохранён: {path}")

    # ================================================================ выделение, группа, ПКМ-редактор
    def _selected(self, v=None) -> list[dict]:
        v = v or self.cur2d()
        sel = set(v.selected)
        return [e for e in v.target() if e["id"] in sel]

    def sel_kind(self, v=None) -> str | None:
        """Что выделено: line, circle (и дуга), rect, block, dim, text, other — один объект; group — несколько."""
        ents = self._selected(v)
        if not ents:
            return None
        insts = {e.get("blk") for e in ents}
        if len(insts) == 1 and None not in insts:
            return "block"
        lines = self._rect_of(ents[0]["id"]) if len(ents) == 4 else None
        if lines and {e["id"] for e in lines} == {e["id"] for e in ents}:
            return "rect"
        if len(ents) == 1:
            return {"line": "line", "circle": "circle", "arc": "circle", "dim": "dim", "diadim": "dim", "raddim": "dim",
                    "angdim": "dim", "text": "text"}.get(ents[0]["type"], "other")
        return "group"

    def open_context_editor(self, v, global_pos):
        """ПКМ по выделенному: компактная панель у курсора с полями (применяются сразу) и быстрыми действиями."""
        if self.ctx_editor is not None:
            self.ctx_editor.close()
        self.ctx_editor = ContextEditor(self, lambda rows: self._build_editor(rows, v, popup=True))
        self.ctx_editor.show_at(global_pos)

    def _build_editor(self, rows: Rows, v, popup: bool) -> bool:
        kind = self.sel_kind(v)
        ents = self._selected(v)
        if kind is None:
            return False
        styles = [(k, STYLE_LABEL[k]) for k in STYLES]
        e = ents[0]
        eid = e["id"]
        if kind == "line":
            rows.title("Отрезок")
            rows.spin("length", "Длина L, мм", params.line_length(e), lambda x: self._set_geom(eid, "length", x), 0.01, 1e5)
            rows.spin("angle", "Угол α, °", params.line_angle(e), lambda x: self._set_geom(eid, "angle", x), -360, 360)
            rows.combo("style", "Стиль линии", styles, e["style"], lambda st: self._set_field(eid, "style", st))
            rows.buttons([("dim", "Поставить размер", lambda: self.ctx_dimension(v, eid)),
                          ("split", "Разделить пополам", lambda: self.ctx_split(v, eid)),
                          ("perp", "Перпендикуляр из середины", lambda: self.ctx_perpendicular(v, eid)),
                          ("move", "Переместить / повернуть…", lambda: self.ctx_move_rotate(v)),
                          ("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить", self.delete_selected)])
        elif kind == "circle":
            rows.title("Окружность" if e["type"] == "circle" else "Дуга")
            rows.spin("d", "Диаметр Ø, мм", 2 * e["r"], lambda x: self._set_geom(eid, "d", x), 0.01, 2e5)
            rows.spin("r", "Радиус R, мм", e["r"], lambda x: self._set_geom(eid, "r", x), 0.01, 1e5)
            rows.check("axes", "Осевые линии центра (крест)", e.get("axes"), lambda on: self._set_field(eid, "axes", on))
            rows.combo("style", "Стиль линии", styles, e["style"], lambda st: self._set_field(eid, "style", st))
            rows.buttons([("dim", "Поставить размер Ø" if e["type"] == "circle" else "Поставить размер R", lambda: self.ctx_dimension(v, eid)),
                          ("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить", self.delete_selected)])
        elif kind == "rect":
            x, y, w, h = params.rect_info(ents)
            rows.title("Прямоугольник")
            rows.spin("w", "Ширина W, мм", w, lambda val: self._set_rect(eid, "w", val), 0.01, 1e5)
            rows.spin("h", "Высота H, мм", h, lambda val: self._set_rect(eid, "h", val), 0.01, 1e5)
            rows.combo("style", "Стиль линии", styles, e["style"], lambda st: self._group_style(v, st))
            rows.buttons([("explode", "Разбить на отдельные линии", lambda: self.ctx_explode(v)),
                          ("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить", self.delete_selected)])
        elif kind == "block":
            inst = e["blk"]
            rows.title(f"⊞ {self._block_name(e)}")
            rows.text("label", "Маркировка", library.label_of(v.target(), inst), lambda s: self._set_block_label(v.target(), inst, s), "QF1, ОП-12, А…")
            at = next((x["blk_at"] for x in ents if x.get("blk_at")), None)
            rows.spin("scale", "Масштаб", at[3] if at else 1.0, lambda k: self.ctx_scale_block(v, k), 0.05, 100, 3, 0.1)
            rows.buttons([("rot_ccw", "Повернуть +90°", lambda: self.ctx_rotate(v, 90)), ("rot_cw", "Повернуть −90°", lambda: self.ctx_rotate(v, -90)),
                          ("explode", "Разрушить блок на примитивы", lambda: self.ctx_explode(v)),
                          ("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить", self.delete_selected)])
        elif kind == "dim":
            rows.title(entity_label(e))
            if params.associative(e):
                rows.spin("value", "Значение (управляющее)", params.dim_value(e), lambda x: self._set_dim_value(eid, x), 0.01, 1e6)
            if e["type"] != "leader":
                rows.text("tol", "Допуск", e.get("tol", ""), lambda s: self._edit(lambda: e.__setitem__("tol", check_tolerance(s))), "H7, ±0,1")
                rows.text("text", "Свой текст", e.get("text", ""), lambda s: self._set_field(eid, "text", s), "Ø40 H7 — вместо числа")
            rows.buttons([("explode", "Разрушить на примитивы", lambda: self.ctx_explode(v)), ("del", "Удалить", self.delete_selected)])
        elif kind == "text":
            rows.title("Надпись")
            rows.text("text", "Текст", e["text"], lambda s: self._set_field(eid, "text", s))
            rows.spin("h", "Высота шрифта, мм", e["h"], lambda x: self._set_geom(eid, "h", x), 0.5, 100)
            rows.buttons([("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить", self.delete_selected)])
        elif kind == "other":
            rows.title(entity_label(e))
            rows.buttons([("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить", self.delete_selected)])
        else:
            n = len(ents)
            rows.title(f"Редактор группы ({n} шт.)" if popup else f"Выбрано объектов: {n}")
            types = {x["type"] for x in ents}
            if types == {"line"}:
                L = selection.common(ents, "length")
                rows.spin("length", "Общая длина L, мм", L if L is not None else params.line_length(e), lambda x: self._group_set(v, "length", x), 0.01, 1e5)
                if L is None:
                    rows.note("Длины разные: новое значение получат все выбранные отрезки")
            elif types <= {"circle", "arc"}:
                D = selection.common(ents, "d")
                rows.spin("d", "Общий диаметр Ø, мм", D if D is not None else 2 * e["r"], lambda x: self._group_set(v, "d", x), 0.01, 2e5)
                if D is None:
                    rows.note("Диаметры разные: новое значение получат все выбранные")
            curves = [x for x in ents if x["type"] in ("line", "circle", "arc")]
            if curves:
                st = {x["style"] for x in curves}
                rows.combo("style", "Стиль линии", styles, st.pop() if len(st) == 1 else None, lambda s: self._group_style(v, s))
            rows.spin("dx", "Сдвиг ΔX, мм", 0.0, lambda _: None)
            rows.spin("dy", "Сдвиг ΔY, мм", 0.0, lambda _: None)
            rows.spin("rot", "Поворот, °", 0.0, lambda _: None, -360, 360)
            rows.buttons([("move", "Сдвинуть на ΔX, ΔY", lambda: self.group_move(v, rows.fields["dx"].value(), rows.fields["dy"].value())),
                          ("rotate", "Повернуть на угол", lambda: self.group_rotate(v, rows.fields["rot"].value())),
                          ("mirror_v", "Отразить ↔", lambda: self.group_mirror(v, "v")), ("mirror_h", "Отразить ↕", lambda: self.group_mirror(v, "h")),
                          ("align_h", "Выровнять по горизонтали", lambda: self.group_align(v, "h")),
                          ("align_v", "Выровнять по вертикали", lambda: self.group_align(v, "v")),
                          ("close", "Замкнуть контур", lambda: self.group_close(v)), ("extrude", "Выдавить в 3D", lambda: self.group_extrude(v)),
                          ("save", "В «Мои элементы»", self.save_to_library), ("copy", "Копировать", self.copy_selection),
                          ("dup", "Дублировать", lambda: self.duplicate_selection(v)), ("del", "Удалить выбранные", self.delete_selected)])
        return True

    # ---- групповые правки (каждая — один шаг Ctrl+Z)
    def _group_set(self, v, key, value):
        ents = [x for x in self._selected(v) if x["type"] in (("line",) if key == "length" else ("circle", "arc"))]
        if ents and selection.common(ents, key) != value:
            self._edit(lambda: selection.set_common(ents, key, value))
            self.hint.setText(f"{'Длина' if key == 'length' else 'Диаметр'} {value:g} мм — у {len(ents)} объектов")

    def _group_style(self, v, style):
        ents = [x for x in self._selected(v) if x["type"] in ("line", "circle", "arc")]
        if ents and any(x["style"] != style for x in ents):
            self._edit(lambda: [x.__setitem__("style", style) for x in ents])

    def group_move(self, v, dx, dy):
        ents = self._selected(v)
        if ents and (dx or dy):
            self._edit(lambda: selection.move(ents, dx, dy))

    def group_rotate(self, v, deg):
        ents = self._selected(v)
        if ents and deg:
            c = selection.center(ents)
            self._edit(lambda: selection.rotate(ents, c, deg))

    def group_mirror(self, v, axis):
        ids = list(v.selected)
        if ids:
            self._edit(lambda: selection.mirror(v.target(), ids, axis))

    def group_align(self, v, axis):
        ents = self._selected(v)
        if ents:
            self._edit(lambda: selection.straighten(ents, axis))

    def group_close(self, v):
        ents = self._selected(v)
        n = []
        if ents and self._edit(lambda: n.append(geo.fix_gaps(ents, 1.0))):
            self.hint.setText(f"Сведено стыков: {n[0]}" if n[0] else "Разрывов до 1 мм между концами отрезков не найдено")

    def group_extrude(self, v):
        """Выдавить в 3D только выбранное: из текущего эскиза контуры уходят в операцию, с листа — копируются."""
        ents = [x for x in self._selected(v) if x["type"] in ("line", "circle", "arc")]
        if not ents:
            warn(self, "Выдавить в 3D", "Выберите замкнутый контур из отрезков, дуг или окружностей")
            return
        if self.edit_fid:
            warn(self, APP, "Сначала закончите редактирование эскиза операции")
            return
        a = ask_form(self, "Выдавить выделенное", [("height", "Высота, мм", "float", 10.0, (0.001, 1e5)), ("op", "Операция", "choice", "add", OPS)])
        if a is None:
            return
        ids = {x["id"] for x in ents}
        own = v is self.sketch and v.target_override is None

        def fn():
            saved = self.project.entities
            self.project.entities = ([x for x in saved if x["id"] in ids] if own
                                     else [{**edit2d._copy(x), "style": "main"} for x in ents])
            try:
                ops.create_feature(self.project, "extrude", **a)
            except ValueError:
                self.project.entities = saved
                raise
            self.project.entities = [x for x in saved if x["id"] not in ids] if own else saved
        v.selected = []
        if self._edit(fn, sketch=True):
            self.refresh(fit3d=True)
            self.work.setCurrentIndex(2)
            self.hint.setText(f"{self.project.features[-1]['name']}: выдавлено выделенное ({len(ents)} объектов)")

    def copy_selection(self):
        v = self.cur2d()
        ids = list(v.selected)
        if not ids:
            self.hint.setText("Нечего копировать: сначала выделите объекты")
            return
        self._clipboard = selection.clip_copy(v.target(), ids)
        QApplication.clipboard().setText(json.dumps({"recad": 1, "entities": self._clipboard}, ensure_ascii=False))
        self.hint.setText(f"Скопировано объектов: {len(ids)} — Ctrl+V вставит у курсора")

    def paste(self):
        clip = self._clipboard
        if not clip:
            try:
                data = json.loads(QApplication.clipboard().text())
                clip = data["entities"] if data.get("recad") else []
            except (ValueError, TypeError, KeyError, AttributeError):
                clip = []
        if not clip:
            self.hint.setText("Буфер пуст: сначала Ctrl+C")
            return
        v = self.cur2d()
        at = v.cursor if v.underMouse() else None
        made = []
        if self._edit(lambda: made.extend(selection.paste(v.target(), clip, at))):
            v.select([x["id"] for x in made])
            self.hint.setText(f"Вставлено объектов: {len(made)}")

    def duplicate_selection(self, v=None):
        v = v or self.cur2d()
        ids = list(v.selected)
        made = []
        if ids and self._edit(lambda: made.extend(selection.duplicate(v.target(), ids))):
            v.select([x["id"] for x in made])

    def ctx_dimension(self, v, eid):
        e = self.project.find(eid)
        if e is not None:
            self._edit(lambda: v.target().append(selection.dimension_for(self.project, e)))

    def ctx_split(self, v, eid):
        made = []
        if self._edit(lambda: made.extend(selection.split_line(v.target(), eid))):
            v.select([x["id"] for x in made])
            self.hint.setText("Отрезок разделён пополам")

    def ctx_perpendicular(self, v, eid):
        made = []
        if self._edit(lambda: made.append(selection.perpendicular(v.target(), eid))):
            v.select([made[0]["id"]])

    def ctx_move_rotate(self, v):
        a = ask_form(self, "Переместить / повернуть", [("dx", "Сдвиг ΔX, мм", "float", 0.0, (-1e5, 1e5)), ("dy", "Сдвиг ΔY, мм", "float", 0.0, (-1e5, 1e5)),
                                                       ("rot", "Поворот, ° (вокруг центра)", "float", 0.0, (-360, 360))])
        ents = self._selected(v)
        if a is None or not ents:
            return

        def fn():
            selection.move(ents, a["dx"], a["dy"])
            if a["rot"]:
                selection.rotate(ents, selection.center(ents), a["rot"])
        self._edit(fn)

    def ctx_rotate(self, v, deg):
        """Элемент библиотеки — вокруг точки вставки, маркировка остаётся горизонтальной."""
        ents = self._selected(v)
        if ents:
            c = selection.block_anchor(ents)
            self._edit(lambda: selection.rotate(ents, c, deg))

    def ctx_scale_block(self, v, k):
        ents = self._selected(v)
        at = next((x["blk_at"] for x in ents if x.get("blk_at")), None)
        cur = at[3] if at else 1.0
        if ents and abs(k - cur) > 1e-9:
            c = selection.block_anchor(ents)
            self._edit(lambda: selection.scale(ents, c, k / cur))

    def ctx_explode(self, v):
        """Разрушить: прямоугольник — на отрезки, элемент библиотеки — на примитивы, размер — на линии и текст."""
        kind = self.sel_kind(v)
        ents = self._selected(v)
        if kind == "rect":
            self._edit(lambda: selection.explode_rect(ents))
            v.select([ents[0]["id"]])
            self.hint.setText("Прямоугольник разбит на 4 отрезка — каждую сторону можно править отдельно")
        elif kind == "block":
            self._edit(lambda: selection.explode_block(v.target(), ents[0]["blk"]))
            self.hint.setText("Элемент разрушен на примитивы")
        elif kind == "dim":
            made = []
            if self._edit(lambda: made.extend(selection.explode_dim(v.target(), ents[0]["id"]))):
                v.select([])
                self.hint.setText(f"Размер разрушен: {len(made)} примитивов")

    # ================================================================ библиотека
    def show_library(self):
        self.library_dock.show()
        self.library_dock.raise_()
        self.library_panel.search.setFocus()
        self.library_panel.search.selectAll()

    # ================================================================ правые панели и «О программе»
    def show_ai(self):
        """ИИ-помощник: всегда его панель — чат, поле запроса, «Настройки…» с ключом API. Не переключатель видимости:
        скрытый помощник в общей с «Библиотекой» области открывал бы соседнюю вкладку."""
        self.ai_dock.show()
        self.ai_dock.raise_()
        self.chat_input.setFocus()

    def front_dock(self) -> QDockWidget | None:
        """Какая из правых панелей сейчас впереди (по вкладкам общей док-области, а не по номеру)."""
        docks = {d.windowTitle(): d for d in (self.ai_dock, self.library_dock)}
        for bar in self.findChildren(QTabBar):
            titles = [bar.tabText(i) for i in range(bar.count())]
            if set(docks) <= set(titles) and bar.currentIndex() >= 0:
                d = docks[bar.tabText(bar.currentIndex())]
                return d if d.isVisible() else None
        shown = [d for d in docks.values() if d.isVisible()]
        return shown[0] if len(shown) == 1 else None

    def about_text(self) -> str:
        t = self.themes.theme
        note = (f'<table width="100%" cellspacing="0" cellpadding="8" bgcolor="{mix(t.panel, t.accent, 0.16)}" '
                f'style="border: 1px solid {t.accent}; color: {t.text}"><tr><td><b>{html.escape(ai.VISION_HINT_TITLE)}</b><br>'
                f'{ai.hint_html(ai.VISION_HINT)}</td></tr></table>')
        return (f'<h2 style="margin: 0 0 6px 0">{APP}</h2>'
                "<p>Лёгкая САПР: 2D-эскиз, чертёж по ЕСКД/ГОСТ, 3D-моделирование и ИИ-помощник.</p>"
                f"{note}"
                f'<p style="color: {t.muted}">Геометрия: manifold3d (Apache-2.0). Интерфейс: Qt for Python (LGPLv3).</p>')

    def show_about(self, run=True) -> QMessageBox:
        box = QMessageBox(QMessageBox.Information, f"О программе «{APP}»", "", QMessageBox.Ok, self)
        box.setTextFormat(Qt.RichText)
        box.setText(self.about_text())
        box.setIconPixmap(self.windowIcon().pixmap(64, 64))
        if run and not Ask.AUTO:
            box.exec()
        else:
            Ask.answers.setdefault("_forms", []).append(box.windowTitle()) if Ask.AUTO else None
        return box

    def choose_template(self):
        self.show_library()
        self.library_panel.search.clear()
        self.library_panel.select("template", next(iter(library.TEMPLATES)))
        self.hint.setText("Шаблоны листов — вверху каталога; двойной щелчок открывает новый документ из шаблона")

    def _hotkey(self, v, tool):
        if tool == "rect" and v.tool == "block":   # при вставке элемента R — поворот, а не прямоугольник
            v.rotate_block(90)
        else:
            self.set_tool(tool)

    def insert_block(self, bid: str, label: str | None = None):
        """Прикрепить элемент к курсору: щелчок ставит, R/Пробел поворачивает. Из 3D — на лист чертежа."""
        if self.work.currentIndex() == 2:
            self.work.setCurrentIndex(1)
        v = self.cur2d()
        try:
            v.start_block(bid, label)
        except ValueError as exc:
            warn(self, "Библиотека", str(exc))
            return
        self.tool_panel.bind(v, "block")
        self._sync_tool_buttons("block")
        v.setFocus()

    def open_template(self, tid: str):
        if not self._confirm_discard():
            return
        project = Project()
        try:
            t = library.load_template(project, tid)
        except ValueError as exc:
            warn(self, "Шаблон", str(exc))
            return
        self._replace_project(project, None)
        self.dirty = True
        self._remember_canvas(project.canvas_mode())
        self.work.setCurrentIndex(1)
        self.sheet.fit_sheet()
        self._title()
        self.hint.setText(f"Шаблон «{t.name}»: двойной щелчок по надписи или графе штампа — правка")

    def save_to_library(self):
        v = self.cur2d()
        sel = set(v.selected)
        ents = [e for e in v.target() if e["id"] in sel]
        if not ents:
            warn(self, "Сохранить в библиотеку", "Выделите на холсте объекты узла (Shift — несколько), затем сохраните")
            return
        a = ask_form(self, "Сохранить в «Мои элементы»", [("name", "Название", "text", "Мой узел"), ("keywords", "Ключевые слова для поиска", "text", "")],
                     f"Объектов: {len(ents)}. Точка вставки — левый нижний угол габарита. Файл: {library.user_path()}")
        if a is None:
            return
        try:
            bid = library.save_user_block(a["name"], ents, a["keywords"])
        except (ValueError, OSError) as exc:
            warn(self, "Сохранить в библиотеку", str(exc))
            return
        self.library_panel.rebuild()
        self.library_panel.select("block", bid)
        self.hint.setText(f"«{a['name']}» сохранён в «Мои элементы»: {library.user_path()}")

    def delete_user_block(self, bid: str):
        name = library.get_block(bid).name
        if not Ask.AUTO and QMessageBox.question(self, "Мои элементы", f"Удалить «{name}» из библиотеки?") != QMessageBox.Yes:
            return
        try:
            library.delete_user_block(bid)
        except (ValueError, OSError) as exc:
            warn(self, "Мои элементы", str(exc))
            return
        self.library_panel.rebuild()
        self.hint.setText(f"«{name}» удалён из «Моих элементов»")

    def _fill_user_menu(self):
        self.user_menu.clear()
        users = list(library.user_blocks().values())
        if not users:
            a = self.user_menu.addAction("(пусто — «Сохранить выделенное в библиотеку»)")
            a.setEnabled(False)
        for b in users:
            self.user_menu.addAction(b.name, lambda bid=b.id: self.insert_block(bid))

    def _set_block_label(self, lst, inst, text):
        if text != library.label_of(lst, inst):
            self._edit(lambda: library.set_label(lst, inst, text))

    # ================================================================ темы
    def show_appearance(self):
        if self.appearance_dlg is None:
            self.appearance_dlg = AppearanceDialog(self.themes, self)
        self.appearance_dlg.show()
        self.appearance_dlg.raise_()
        self.appearance_dlg.activateWindow()

    def _tone(self, color: str) -> str:
        t = self.themes.theme
        return readable(color, mix(mix(t.bg1, t.bg2, 0.5), t.panel, t.panel_alpha), 4.5)

    def _on_theme(self, theme):
        if hasattr(self, "library_panel"):
            self.library_panel.apply_theme(theme.text, theme.ink, theme.paper1)
        self.sketch.apply_theme(theme)
        self.sheet.apply_theme(theme)
        self.view3d.apply_theme(theme)
        for b, glyph in self.glyph_buttons:
            b.setIcon(glyph_icon(glyph, theme.text))
        # Каждый выбор темы сразу в config.json (рядом с .exe): при перезапуске она вернётся.
        if self.cfg.get("appearance") != self.themes.settings() or self.cfg.get("active_theme") != self.themes.active_id():
            self.cfg["appearance"] = self.themes.settings()
            self.cfg["active_theme"] = self.themes.active_id()
            if not self._save_cfg("appearance", "active_theme"):
                self.hint.setText(f"Не удалось сохранить оформление в {ai.config_path()}")

    def _sync_theme(self):
        """Поля берут цвета только из ThemeManager; при переключении вкладки или полотна — сверка с активной темой."""
        for v in (self.sketch, self.sheet, self.view3d):
            v.apply_theme(self.themes.theme, force=False)

    # ================================================================ ИИ
    def _chat_note(self, text, color=None):
        color = color or self.themes.theme.muted
        self.chat_view.append(f'<p style="color:{color};margin:4px 0">{html.escape(text).replace(chr(10), "<br>")}</p>')

    def _chat_msg(self, who, text, color):
        self.chat_view.append(f'<p style="margin:6px 0"><b style="color:{color}">{who}:</b> {html.escape(text).replace(chr(10), "<br>")}</p>')

    def _clear_chat(self):
        self.chat.clear()
        self.chat_view.clear()

    def ai_settings(self):
        dlg = AISettingsDialog(self.cfg, self)
        if Ask.AUTO:  # автотест: окно собирается, но не показывается
            Ask.answers.setdefault("_forms", []).append(dlg.windowTitle())
            dlg.deleteLater()
            return
        if dlg.exec() == QDialog.Accepted:
            self.cfg.update(dlg.result_cfg)
            try:
                ai.update_config(dlg.result_cfg)
                self.hint.setText(f"Настройки ИИ сохранены: {ai.config_path()}")
            except OSError as exc:
                QMessageBox.warning(self, "Настройки ИИ", f"Не удалось записать {ai.config_path()}:\n{exc}")

    # ---------------------------------------------------------------- вложения
    def attach_dialog(self, kind: str = "all") -> bool:
        """Системный выбор файлов: фото, Word, текст. True — что-то выбрано."""
        if Ask.AUTO:
            paths = list(Ask.answers.get("attach.paths", []))
        else:
            flt = ";;".join([attachments.FILTERS[kind]] + [f for k, f in attachments.FILTERS.items() if k != kind])
            start = getattr(self, "_attach_dir", None) or self._dir()
            paths, _ = QFileDialog.getOpenFileNames(self, "Прикрепить фото или документ", start, flt)
        if paths:
            self._attach_dir = os.path.dirname(paths[0])
            self.attach_files(paths)
        return bool(paths)

    def attach_files(self, paths: list[str]):
        self._start_attach([("path", p) for p in paths])

    def attach_image(self, img: QImage):
        """Скриншот из буфера обмена или картинка, перетащенная из браузера."""
        self._attach_seq += 1
        self._start_attach([("png", png_bytes(img), f"Скриншот {self._attach_seq}.png")])

    def _start_attach(self, jobs):
        worker = AttachWorker(jobs, self)
        worker.loaded.connect(self._attached)
        worker.failed.connect(lambda msg: self._chat_note("📎 " + msg, self._tone("#c22f2f")))
        worker.finished.connect(lambda wk=worker: self._attach_finished(wk))
        self._attach_workers.append(worker)
        self.ai_status.setText("⏳ Обработка вложений: сжатие фото, разбор документа, анализ контуров…")
        self._update_send_state()
        worker.start()

    def _attached(self, items: list):
        room = ai.MAX_IMAGES - sum(1 for a in self.attachments if a.kind == "image")
        keep = []
        for a in items:
            if a.kind == "image":
                if room <= 0:
                    self._chat_note(f"📎 «{a.name}» не прикреплено: не больше {ai.MAX_IMAGES} картинок в сообщении", self._tone("#c22f2f"))
                    continue
                room -= 1
            keep.append(a)
        doc = next((a for a in keep if a.kind == "docx"), None)
        if doc is not None and doc.info.get("skipped"):
            self._chat_note(f"📎 «{doc.name}»: рисунков {doc.info['images']}, приложено {doc.info['attached']} "
                            f"(остальные — значки, векторные EMF/WMF или сверх {attachments.MAX_DOC_IMAGES})")
        self.attachments.extend(keep)
        self.attach_bar.set_items(self.attachments)

    def _attach_finished(self, worker):
        if worker in self._attach_workers:
            self._attach_workers.remove(worker)
        worker.deleteLater()
        if self._attach_workers:
            return
        busy = self.worker is not None and self.worker.isRunning()
        if not busy:
            self.ai_status.setText(f"📎 Вложений: {len(self.attachments)} — отправятся со следующим сообщением" if self.attachments else "")
        self._update_send_state()
        key, self._pending_preset = self._pending_preset, None
        if key and self._preset_ready(key):
            self._send_preset(key)

    def wait_attachments(self, timeout_ms: int = 30000):
        """Дождаться обработки вложений (автотесты и самопроверка сборки)."""
        for _ in range(5):
            if not self._attach_workers:
                break
            for wk in list(self._attach_workers):
                wk.wait(timeout_ms)
            QApplication.processEvents()
            QApplication.processEvents()

    def remove_attachment(self, i: int):
        if not 0 <= i < len(self.attachments):
            return
        att = self.attachments.pop(i)
        if att.kind == "docx":                      # с документом уходят и его рисунки
            self.attachments = [a for a in self.attachments if a.parent != att.name]
        self.attach_bar.set_items(self.attachments)
        if not self.attachments and not (self.worker and self.worker.isRunning()):
            self.ai_status.setText("")

    def _drop_hover(self, on: bool):
        w = self.ai_panel
        w.setProperty("dropping", bool(on))
        w.style().unpolish(w)
        w.style().polish(w)
        if on:
            self.ai_status.setText("Отпустите — фото или документ прикрепится к сообщению")
        elif not self._attach_workers and not (self.worker and self.worker.isRunning()):
            self.ai_status.setText("")

    def _update_send_state(self):
        self.ai_send_btn.setEnabled(not self._attach_workers and not (self.worker and self.worker.isRunning()))

    def _preset_ready(self, key) -> bool:
        need = next(p[2] for p in ai.ATTACH_PRESETS if p[0] == key)
        return any((a.kind == "image") == (need == "image") for a in self.attachments)

    def ai_preset(self, key: str):
        """Быстрый сценарий: нужного вложения нет — выбор файла, затем запрос уходит сам. Набранный текст — дополнение."""
        if self.worker and self.worker.isRunning():
            return
        need = next(p[2] for p in ai.ATTACH_PRESETS if p[0] == key)
        if self._attach_workers:                    # вложения ещё обрабатываются — отправим, когда будут готовы
            self._pending_preset = key
            return
        if not self._preset_ready(key):
            self._pending_preset = key
            if not self.attach_dialog("image" if need == "image" else "doc"):
                self._pending_preset = None
            return
        self._send_preset(key)

    def _send_preset(self, key: str):
        _, label, _, prompt = next(p for p in ai.ATTACH_PRESETS if p[0] == key)
        typed = self.chat_input.toPlainText().strip()
        self.ai_send(prompt + (f"\nДополнительно от пользователя: {typed}" if typed else ""), shown=label + (f". {typed}" if typed else ""))

    def _chat_attachments(self, atts):
        """Миниатюры отправленных фото и имена документов в переписке."""
        doc = self.chat_view.document()
        cells = []
        for a in atts:
            if a.kind == "image":
                self._attach_seq += 1
                url = QUrl(f"att://img{self._attach_seq}")
                doc.addResource(QTextDocument.ImageResource, url, QImage.fromData(a.thumb or a.data))
                cells.append(f'<img src="{url.toString()}" height="56"> ')
            else:
                cells.append(f"<b>[{a.badge}]</b> ")
        names = ", ".join(html.escape(a.name) for a in atts)
        self.chat_view.append(f'<p style="margin:2px 0">{"".join(cells)}</p>'
                              f'<p style="color:{self.themes.theme.muted};margin:0 0 4px 0">📎 {names}</p>')

    def ai_send(self, text: str | None = None, shown: str | None = None):
        """Отправить запрос; вложения из ленты уходят вместе с ним (фото — картинками, документы — текстом)."""
        typed = self.chat_input.toPlainText().strip()
        text = typed if text is None else text
        if self.worker and self.worker.isRunning():
            return
        if self._attach_workers:
            self.ai_status.setText("⏳ Дождитесь обработки вложений — запрос уйдёт вместе с ними")
            return
        atts = list(self.attachments)
        if not text and not atts:
            return
        text = text or "Посмотри вложения и начерти по ним чертёж в мм с размерами."
        self.chat_input.clear()
        self._chat_msg("Вы", shown or text, self.themes.theme.accent_text)
        if atts:
            self._chat_attachments(atts)
            self.attachments = []
            self.attach_bar.set_items([])
        self._sent_attachments = atts
        self._ai_layer = "drawing" if self.cur2d() is self.sheet and self.work.currentIndex() == 1 else "sketch"
        system = ai.build_system_prompt(self.project, self.solid, self._ai_view().target(), self._ai_layer)
        content = ai.user_content(text, atts)
        messages = ai.compact_history(self.chat[-12:] + [{"role": "user", "content": content}])
        self.chat.append({"role": "user", "content": content})
        self.worker = ai.AIWorker(self.cfg, system, messages, self)
        self.worker.done.connect(self._ai_done)
        self.worker.failed.connect(self._ai_failed)
        self.worker.finished.connect(lambda: (self._update_send_state(), self.ai_status.setText("")))
        self.ai_send_btn.setEnabled(False)
        pics = sum(1 for a in atts if a.kind == "image")
        extra = f" Вложений: {len(atts)}" + (f", из них фото {pics}" if pics else "") + "." if atts else ""
        self.ai_status.setText(f"⏳ {ai.PROVIDERS.get(self.cfg['provider'])} · {self.cfg.get('model')} думает…{extra} Можно продолжать чертить.")
        self.worker.start()

    def _ai_done(self, reply: dict):
        self._sent_attachments = []
        self.chat.append({"role": "assistant", "content": reply.get("raw", "")})
        self._chat_msg("Помощник", reply.get("message") or "(без пояснения)", self._tone("#1d7748"))
        actions = reply.get("actions", [])
        if not actions:
            return
        if not self.ai_apply.isChecked():
            self._chat_note(f"Команд в ответе: {len(actions)} — выполнение выключено.")
            return
        self.history.push()
        log = ops.apply_actions(self.project, actions, self._ai_view().target())
        self.dirty = True
        made_3d = any(a.get("op") in ("extrude", "cut", "cut_extrude", "revolve", "shell", "fillet3d", "chamfer3d") for a in actions)
        to_sheet = any(a.get("op") in ("load_template", "set_canvas", "add_frame") for a in actions)
        self.refresh(fit3d=made_3d)
        if to_sheet:
            self._remember_canvas(self.project.canvas_mode())
            self.work.setCurrentIndex(1)
            self.sheet.fit_sheet()
        elif made_3d:
            self.work.setCurrentIndex(2)
        else:
            self.cur2d().fit_all()
        self._chat_note("\n".join(log))
        for f in self.project.features:
            if self.solid.statuses.get(f["id"]):
                self._chat_note(f"⚠ {f['name']}: {self.solid.statuses[f['id']]}", self._tone("#c22f2f"))

    def _ai_view(self) -> SketchView:
        """Куда пишет помощник: открыт лист — на лист, иначе в эскиз (запоминается при отправке)."""
        return self.sheet if getattr(self, "_ai_layer", "sketch") == "drawing" else self.sketch

    def _ai_failed(self, msg: str):
        if self.chat and self.chat[-1]["role"] == "user":
            self.chat.pop()
        self._chat_msg("Ошибка", msg, self._tone("#c22f2f"))
        if self._sent_attachments and not self.attachments:    # вложения не пропадают: можно отправить ещё раз
            self.attachments, self._sent_attachments = self._sent_attachments, []
            self.attach_bar.set_items(self.attachments)
            self._chat_note(f"Вложения ({len(self.attachments)}) возвращены в поле ввода — можно отправить ещё раз.")

    # ================================================================ закрытие
    def closeEvent(self, ev):
        if not self._confirm_discard():
            ev.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.worker.wait(3000)
        for wk in list(self._attach_workers):
            wk.wait(3000)
        if not Ask.AUTO:
            QSettings("ReCAD", "desktop").setValue("geometry", self.saveGeometry())
        ev.accept()
