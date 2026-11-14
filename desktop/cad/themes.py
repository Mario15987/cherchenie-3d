"""Цветовые темы: пресеты, вывод полной палитры из трёх цветов, QSS для всего приложения, цвета чертежа и 3D.

Любая тема задаётся тремя цветами: фон, второй цвет градиента, акцент. Остальное (панели, текст, линии чертежа,
сетка, фон 3D) выводится из них с учётом того, светлая тема или тёмная, — так же работает и «Своя тема».
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    bg1: str
    bg2: str
    accent: str


CLASSIC_LIGHT = Preset("classic-light", "Светлая классическая", "#eef1f5", "#eef1f5", "#1e5ccc")
CLASSIC_DARK = Preset("classic-dark", "Тёмная классическая", "#1b1f26", "#1b1f26", "#4c9bff")

PASTEL = [
    Preset("mint", "Мятный бриз", "#dcf5ea", "#b9e7d4", "#1d8a66"),
    Preset("peach", "Персиковый рассвет", "#ffe6d6", "#ffc8ad", "#c9531f"),
    Preset("lavender", "Небесно-лавандовый", "#dce8ff", "#e4d9ff", "#5a52d0"),
    Preset("lemon", "Лимонный сорбет", "#fff9d4", "#f8e7a2", "#946d00"),
    Preset("dusty-rose", "Пыльная роза", "#f4e2e3", "#e3c3c7", "#a3405a"),
    Preset("rose-quartz", "Розовый кварц", "#fde6f1", "#efcde4", "#b8336f"),
    Preset("ice-cyan", "Ледяной циан", "#ddf7fb", "#c2e9f3", "#08788f"),
    Preset("cream", "Тёплый кремовый (ватман)", "#fcf8ee", "#f1e8d3", "#85561a"),
]

DARK = [
    Preset("crimson", "Багрово-чёрный", "#0d0d10", "#3b0b14", "#ff4d61"),
    Preset("cyberpunk", "Киберпанк", "#1b0b40", "#062a63", "#21e6ff"),
    Preset("sunset", "Закат", "#2d1158", "#8c3a1b", "#ffb04d"),
    Preset("emerald-gold", "Изумрудно-золотой", "#05261f", "#0f4a36", "#e8c159"),
    Preset("midnight", "Глубокий полночный синий", "#070d20", "#13284f", "#5b9bff"),
    Preset("chocolate", "Тёмный шоколад", "#1d120c", "#3c261a", "#e2a96e"),
    Preset("graphite", "Стальной графит", "#1a1d22", "#323842", "#9cc0e4"),
    Preset("pine-fog", "Хвойный туман", "#0e1c18", "#26392f", "#94d6ad"),
    Preset("aurora", "Северное сияние", "#061a2a", "#2b1e5c", "#6ff7c5"),
    Preset("royal-indigo", "Королевский индиго", "#130f3b", "#2c2080", "#c0afff"),
    Preset("volcanic", "Вулканический пепел", "#191615", "#3d2a22", "#ff7043"),
    Preset("abyss", "Океанская бездна", "#02171f", "#05394d", "#45d6e6"),
    Preset("plum", "Сливовый бархат", "#220a20", "#4b1742", "#f283d6"),
    Preset("copper", "Медный терминал", "#0f1315", "#22302f", "#e8934f"),
]

PRESETS = {p.id: p for p in [CLASSIC_LIGHT, CLASSIC_DARK, *PASTEL, *DARK]}


# ---------------------------------------------------------------- цветовая арифметика
def _c(h: str) -> QColor:
    return QColor(h)


def mix(a: str, b: str, t: float) -> str:
    """Смешивает цвета: t=0 — a, t=1 — b."""
    x, y = _c(a), _c(b)
    return QColor(round(x.red() + (y.red() - x.red()) * t), round(x.green() + (y.green() - x.green()) * t),
                  round(x.blue() + (y.blue() - x.blue()) * t)).name()


def luminance(h: str) -> float:
    c = _c(h)

    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(fg: str, bg: str, target: float = 4.5) -> str:
    """Подтягивает цвет к чёрному или белому, пока контраст с фоном не дойдёт до target."""
    toward = "#000000" if luminance(bg) > 0.4 else "#ffffff"
    t = 0.0
    while contrast(fg, bg) < target and t < 1:
        t += 0.05
        fg = mix(fg, toward, t)
    return fg


def rgba(h: str, a: float) -> str:
    c = _c(h)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(a * 255)})"


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    dark: bool
    bg1: str
    bg2: str
    accent: str
    panel: str          # цвет полупрозрачных панелей (без альфы)
    panel_alpha: float
    text: str
    muted: str
    border: str
    accent_text: str    # акцент, читаемый на панели
    on_accent: str
    # рабочее поле
    paper1: str
    paper2: str
    grid_minor: str
    grid_major: str
    ink: str
    dim: str
    select: str
    preview: str
    axis_x: str
    axis_y: str
    # 3D
    view3d_bg: str
    view3d_grid: str
    body: str
    edge: str


def derive(p: Preset, classic_canvas: bool = False) -> Theme:
    mid = mix(p.bg1, p.bg2, 0.5)
    dark = luminance(mid) < 0.3
    if dark:
        panel, alpha, text = "#000000", 0.32, "#eef2f7"
        muted = mix(text, mid, 0.35)
        border = mix(mid, "#ffffff", 0.16)
    else:
        panel, alpha, text = "#ffffff", 0.66, "#141a24"
        muted = mix(text, mid, 0.42)
        border = mix(mid, "#000000", 0.14)
    surface = mix(mid, panel, alpha)  # как панель выглядит поверх фона — для проверки контраста
    accent_text = readable(p.accent, surface, 4.5)
    on_accent = "#ffffff" if contrast("#ffffff", p.accent) >= contrast("#000000", p.accent) else "#000000"
    muted = readable(muted, surface, 4.5)

    if classic_canvas or p.id.startswith("classic"):
        base = CLASSIC_DARK if dark else CLASSIC_LIGHT
        paper1 = paper2 = "#16191e" if dark else "#fbfbf8"
        accent_canvas = base.accent
    else:
        # Светлые темы — светлый лист в тон темы; тёмные — тёмное поле в тон градиента.
        paper1, paper2 = (mix(p.bg1, "#000000", 0.18), mix(p.bg2, "#000000", 0.25)) if dark else (mix(p.bg1, "#ffffff", 0.55), mix(p.bg2, "#ffffff", 0.6))
        accent_canvas = p.accent
    paper_mid = mix(paper1, paper2, 0.5)
    if dark:
        ink = readable(mix("#ffffff", accent_canvas, 0.12), paper_mid, 9)
        dim = readable(mix(accent_canvas, "#ffffff", 0.25), paper_mid, 4.5)
        grid_minor, grid_major = mix(paper_mid, "#ffffff", 0.07), mix(paper_mid, "#ffffff", 0.16)
        select, axis_x, axis_y = "#ffb224", "#ff6b6b", "#5fdc8f"
        body, edge = "#b9c3d1", "#0b0d12"
    else:
        ink = readable(mix("#0f2240", accent_canvas, 0.15), paper_mid, 10)
        dim = readable(mix(accent_canvas, "#000000", 0.2), paper_mid, 4.5)
        grid_minor, grid_major = mix(paper_mid, ink, 0.08), mix(paper_mid, ink, 0.2)
        select, axis_x, axis_y = "#d97a00", "#cf3b3b", "#23864c"
        body, edge = "#aeb9c8", "#121822"
    preview = readable(accent_canvas, paper_mid, 3)
    view3d_bg = paper_mid if not dark else mix(paper1, paper2, 0.4)
    return Theme(p.id, p.name, dark, p.bg1, p.bg2, p.accent, panel, alpha, text, muted, border, accent_text, on_accent,
                 paper1, paper2, grid_minor, grid_major, ink, dim, select, preview, axis_x, axis_y,
                 view3d_bg, mix(view3d_bg, "#ffffff" if dark else "#000000", 0.18), body, edge)


# ---------------------------------------------------------------- QSS
def qss(t: Theme) -> str:
    grad = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.bg1}, stop:1 {t.bg2})"
    pnl = rgba(t.panel, t.panel_alpha)
    pnl2 = rgba(t.panel, min(t.panel_alpha + 0.18, 0.92))
    field = rgba(t.panel, min(t.panel_alpha + 0.24, 0.95)) if t.dark else rgba("#ffffff", 0.9)
    hover = rgba(t.accent, 0.16)
    checked = rgba(t.accent, 0.28)
    solid_menu = mix(mix(t.bg1, t.bg2, 0.5), t.panel, t.panel_alpha + 0.2)
    return f"""
QWidget {{ color: {t.text}; background: transparent; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
/* Градиент — после общего правила для QWidget: при равной специфичности побеждает последнее. */
QMainWindow, QDialog, QColorDialog {{ background: {grad}; }}
QTabWidget#ribbon > QTabBar {{ background: {pnl}; }}
QToolTip {{ background: {solid_menu}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
QMenuBar {{ background: {pnl}; border-bottom: 1px solid {t.border}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {hover}; border-radius: 3px; }}
QMenu {{ background: {solid_menu}; border: 1px solid {t.border}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 18px; border-radius: 3px; }}
QMenu::item:selected {{ background: {checked}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
QTabWidget#ribbon::pane {{ border: 0; border-bottom: 1px solid {t.border}; background: {pnl2}; }}
QTabWidget#ribbon > QTabBar::tab {{ padding: 5px 14px; border: 0; background: transparent; color: {t.muted}; }}
QTabWidget#ribbon > QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent_text}; }}
QToolButton {{ border: 1px solid transparent; border-radius: 4px; padding: 2px; }}
QToolButton:hover {{ background: {hover}; border-color: {t.border}; }}
QToolButton:checked {{ background: {checked}; border-color: {t.accent}; }}
QLabel#groupCaption {{ color: {t.muted}; font-size: 8pt; }}
QLabel#hint {{ color: {t.muted}; }}
QWidget#sep {{ background: {t.border}; }}
QLabel#panelTitle {{ background: {pnl2}; color: {t.muted}; font-size: 8pt; font-weight: 600; padding: 4px 8px; border-bottom: 1px solid {t.border}; }}
QWidget#leftPanel, QWidget#aiPanel {{ background: {pnl}; }}
QTreeWidget, QTextBrowser, QScrollArea#themes {{ background: {pnl}; border: 1px solid {t.border}; border-radius: 4px; }}
QPlainTextEdit, QLineEdit, QDoubleSpinBox, QComboBox {{ background: {field}; border: 1px solid {t.border}; border-radius: 4px; padding: 2px 4px; }}
QComboBox QAbstractItemView {{ background: {solid_menu}; border: 1px solid {t.border}; }}
QTreeWidget::item {{ height: 22px; }}
QTreeWidget::item:selected {{ background: {checked}; color: {t.text}; }}
QTreeWidget::item:hover {{ background: {hover}; }}
QLineEdit:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {t.accent_text}; }}
QPushButton {{ background: {field}; border: 1px solid {t.border}; border-radius: 4px; padding: 4px 12px; }}
QPushButton:hover {{ border-color: {t.accent_text}; }}
QPushButton:checked, QPushButton#primary {{ background: {t.accent}; color: {t.on_accent}; border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.muted}; }}
QPushButton#preset {{ text-align: left; padding: 3px 8px; }}
QToolButton#docTile {{ background: {field}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px 2px; }}
QToolButton#docTile:hover {{ border: 2px solid {t.accent}; background: {hover}; }}
QWidget#tipBox {{ background: {checked}; border: 1px solid {t.border}; border-radius: 6px; }}
QLabel#visionNote {{ background: {checked}; border: 1px solid {t.accent}; border-radius: 4px; padding: 4px 6px; }}
QFrame#attachChip {{ background: {field}; border: 1px solid {t.border}; border-radius: 6px; }}
QLabel#chipSub {{ color: {t.muted}; font-size: 8pt; }}
QToolButton#chipClose {{ font-size: 12pt; padding: 0 3px; color: {t.muted}; }}
QToolButton#chipClose:hover {{ color: {t.text}; background: {hover}; }}
QScrollArea#attachBar, QWidget#attachInner {{ background: transparent; border: 0; }}
QWidget#aiPanel[dropping="true"] {{ border: 2px dashed {t.accent_text}; border-radius: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t.border}; border-radius: 3px; background: {field}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ padding: 5px 14px; background: {pnl}; border: 1px solid {t.border}; border-bottom: 0; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; color: {t.muted}; }}
QTabBar::tab:selected {{ background: {pnl2}; color: {t.text}; }}
QStatusBar {{ background: {pnl2}; border-top: 1px solid {t.border}; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {pnl2}; padding: 4px 8px; }}
QSplitter::handle {{ background: {t.border}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {rgba(t.text, 0.25)}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {rgba(t.text, 0.25)}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def apply_palette(app: QApplication, t: Theme) -> None:
    """Палитра для того, что QSS не покрывает (стандартные диалоги, курсоры выделения)."""
    pal = QPalette()
    base = mix(mix(t.bg1, t.bg2, 0.5), t.panel, t.panel_alpha + 0.2)
    for role, col in ((QPalette.Window, base), (QPalette.Base, base), (QPalette.AlternateBase, mix(base, t.text, 0.05)),
                      (QPalette.Text, t.text), (QPalette.WindowText, t.text), (QPalette.ButtonText, t.text),
                      (QPalette.Button, base), (QPalette.Highlight, t.accent), (QPalette.HighlightedText, t.on_accent),
                      (QPalette.ToolTipBase, base), (QPalette.ToolTipText, t.text), (QPalette.PlaceholderText, t.muted)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)


class ThemeManager(QObject):
    """Хранит выбранную тему, применяет её к приложению и сообщает рабочим полям о смене цветов."""
    changed = Signal(object)  # Theme

    def __init__(self, settings: dict, active_theme: str | None = None):
        super().__init__()
        self.mode = settings.get("mode", "classic-light")           # classic-light | classic-dark | preset | custom
        self.preset_id = settings.get("preset", "mint")
        if "mode" not in settings and active_theme:                 # в config.json только active_theme
            if active_theme in ("classic-light", "classic-dark", "custom"):
                self.mode = active_theme
            elif active_theme in PRESETS:
                self.mode, self.preset_id = "preset", active_theme
        cu = settings.get("custom") or {}
        self.custom = Preset("custom", "Своя тема", cu.get("bg1", "#1d2b3a"), cu.get("bg2", "#3a2350"), cu.get("accent", "#59d0ff"))
        self.classic_canvas = bool(settings.get("classic_canvas", False))
        self.theme = self._resolve()

    def preset(self) -> Preset:
        if self.mode == "classic-light":
            return CLASSIC_LIGHT
        if self.mode == "classic-dark":
            return CLASSIC_DARK
        if self.mode == "custom":
            return self.custom
        return PRESETS.get(self.preset_id, PASTEL[0])

    def _resolve(self) -> Theme:
        return derive(self.preset(), self.classic_canvas)

    def active_id(self) -> str:
        """Короткое имя активной темы для config.json: classic-light, classic-dark, custom или id пресета."""
        return self.preset_id if self.mode == "preset" else self.mode

    def settings(self) -> dict:
        return {"mode": self.mode, "preset": self.preset_id, "classic_canvas": self.classic_canvas,
                "custom": {"bg1": self.custom.bg1, "bg2": self.custom.bg2, "accent": self.custom.accent}}

    def set(self, mode: str | None = None, preset_id: str | None = None, custom: Preset | None = None, classic_canvas: bool | None = None):
        if mode is not None:
            self.mode = mode
        if preset_id is not None:
            self.preset_id = preset_id
        if custom is not None:
            self.custom = custom
        if classic_canvas is not None:
            self.classic_canvas = classic_canvas
        self.apply()

    def apply(self):
        self.theme = self._resolve()
        app = QApplication.instance()
        if app is not None:
            apply_palette(app, self.theme)
            app.setStyleSheet(qss(self.theme))
        self.changed.emit(self.theme)
