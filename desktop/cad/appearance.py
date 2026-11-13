"""Окно «Внешний вид и цветовые темы»: классические режимы, сетка карточек тем, своя тема."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QColorDialog, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .themes import DARK, PASTEL, Preset, ThemeManager, luminance, mix

CARD = 68   # сторона карточки
PAD = 6     # поле вокруг карточки под обводку и значок


class ThemeCard(QAbstractButton):
    """Скруглённый квадрат с диагональным градиентом темы. Активная — с яркой обводкой и значком ✓."""

    def __init__(self, preset: Preset, custom: bool = False, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.custom = custom
        self.active = False
        self.setFixedSize(QSize(CARD + 2 * PAD, CARD + 2 * PAD))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Своя тема — выбрать свои цвета" if custom else preset.name)
        self.setAccessibleName(self.toolTip())
        self.setFocusPolicy(Qt.StrongFocus)

    def set_preset(self, preset: Preset):
        self.preset = preset
        self.update()

    def set_active(self, on: bool):
        self.active = on
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(PAD, PAD, CARD, CARD)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(self.preset.bg1))
        g.setColorAt(1, QColor(self.preset.bg2))
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, g)
        light = luminance(mix(self.preset.bg1, self.preset.bg2, 0.5)) > 0.3
        # Акцент темы — точка в нижнем левом углу.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.preset.accent))
        p.drawEllipse(QRectF(r.left() + 8, r.bottom() - 18, 10, 10))
        # Тонкая обводка, при наведении — заметнее.
        edge = QColor(0, 0, 0, 40) if light else QColor(255, 255, 255, 45)
        if self.underMouse() or self.hasFocus():
            edge = QColor(0, 0, 0, 110) if light else QColor(255, 255, 255, 140)
        p.setPen(QPen(edge, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if self.custom:
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(26)
            p.setFont(f)
            p.setPen(QColor("#ffffff" if not light else "#1b2230"))
            p.drawText(r.adjusted(0, -6, 0, -6), Qt.AlignCenter, "🎨")
            badge = QRectF(r.center().x() - 19, r.bottom() - 17, 38, 13)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(badge, 6, 6)
            f2 = QFont("Segoe UI")
            f2.setPixelSize(9)
            f2.setBold(True)
            p.setFont(f2)
            p.setPen(QColor("#ffffff"))
            p.drawText(badge, Qt.AlignCenter, "СВОЯ")
        if self.active:
            ring = QPainterPath()
            ring.addRoundedRect(r.adjusted(-3, -3, 3, 3), 16, 16)
            p.setPen(QPen(QColor(self.preset.accent), 3))
            p.drawPath(ring)
            p.setPen(QPen(QColor("#ffffff" if not light else "#10141a"), 1.2))
            p.drawPath(path)
            # Круглый значок с галочкой в правом верхнем углу.
            c = QRectF(r.right() - 13, r.top() - 7, 20, 20)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(QColor(self.preset.accent))
            p.drawEllipse(c)
            f3 = QFont("Segoe UI")
            f3.setPixelSize(12)
            f3.setBold(True)
            p.setFont(f3)
            on_accent = "#000000" if luminance(self.preset.accent) > 0.45 else "#ffffff"
            p.setPen(QColor(on_accent))
            p.drawText(c, Qt.AlignCenter, "✓")
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class CustomThemeDialog(QDialog):
    """Свои цвета: основной фон, второй цвет градиента, акцент. Каждое изменение сразу видно во всём приложении."""
    picked = Signal(object)  # Preset

    def __init__(self, preset: Preset, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Своя тема")
        self.colors = {"bg1": preset.bg1, "bg2": preset.bg2, "accent": preset.accent}
        self.preview = ThemeCard(preset, custom=True)
        self.preview.setEnabled(False)
        form = QFormLayout()
        self.buttons = {}
        for key, label in (("bg1", "Основной фон"), ("bg2", "Второй цвет градиента"), ("accent", "Цвет акцента")):
            b = QPushButton()
            b.setFixedSize(120, 26)
            b.clicked.connect(lambda _=False, k=key, l=label: self._pick(k, l))
            self.buttons[key] = b
            form.addRow(label, b)
        row = QHBoxLayout()
        row.addWidget(self.preview)
        row.addLayout(form, 1)
        done = QPushButton("Готово")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        v = QVBoxLayout(self)
        v.addLayout(row)
        hint = QLabel("Тема собирается из этих трёх цветов: панели, текст и линии чертежа подбираются так, чтобы оставаться читаемыми.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addWidget(done, 0, Qt.AlignRight)
        self._sync()

    def _preset(self) -> Preset:
        return Preset("custom", "Своя тема", self.colors["bg1"], self.colors["bg2"], self.colors["accent"])

    def _sync(self):
        for key, b in self.buttons.items():
            fg = "#000000" if luminance(self.colors[key]) > 0.4 else "#ffffff"
            b.setText(self.colors[key].upper())
            b.setStyleSheet(f"background:{self.colors[key]}; color:{fg}; border:1px solid rgba(127,127,127,0.6); border-radius:4px;")
        self.preview.set_preset(self._preset())

    def _pick(self, key, label):
        c = QColorDialog.getColor(QColor(self.colors[key]), self, label)
        if c.isValid():
            self.colors[key] = c.name()
            self._sync()
            self.picked.emit(self._preset())


class AppearanceDialog(QDialog):
    """Немодальное окно: тема применяется сразу по щелчку, окно можно держать открытым."""

    def __init__(self, themes: ThemeManager, parent=None):
        super().__init__(parent)
        self.themes = themes
        self.setWindowTitle("Внешний вид и цветовые темы")
        self.setMinimumSize(340, 560)

        self.mode_group = QButtonGroup(self)
        modes = QHBoxLayout()
        modes.setSpacing(4)
        self.mode_buttons = {}
        for key, text in (("classic-light", "Светлая\nклассическая"), ("classic-dark", "Тёмная\nклассическая"), ("themes", "Цветовые\nтемы")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setMinimumHeight(40)
            self.mode_group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self._mode(k))
            self.mode_buttons[key] = b
            modes.addWidget(b)

        self.current = QLabel()
        self.current.setObjectName("hint")

        grid_box = QWidget()
        gv = QVBoxLayout(grid_box)
        gv.setContentsMargins(8, 8, 8, 8)
        self.cards: list[ThemeCard] = []
        self.custom_card = ThemeCard(themes.custom, custom=True)
        self.custom_card.clicked.connect(self._open_custom)
        gv.addWidget(self._caption("Светлые"))
        gv.addLayout(self._grid([self.custom_card] + [self._card(p) for p in PASTEL]))
        gv.addWidget(self._caption("Тёмные и насыщенные"))
        gv.addLayout(self._grid([self._card(p) for p in DARK]))
        gv.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("themes")
        scroll.setWidget(grid_box)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.classic_canvas = QCheckBox("Оставить классический фон чертежа (белый/чёрный)")
        self.classic_canvas.setToolTip("Тема красит только панели интерфейса; лист чертежа и 3D-поле остаются классическими")
        self.classic_canvas.setChecked(themes.classic_canvas)
        self.classic_canvas.toggled.connect(lambda on: self.themes.set(classic_canvas=on))

        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        v = QVBoxLayout(self)
        v.addLayout(modes)
        v.addWidget(self.current)
        v.addWidget(scroll, 1)
        v.addWidget(self.classic_canvas)
        v.addWidget(close, 0, Qt.AlignRight)
        themes.changed.connect(self._sync)
        self._sync()

    @staticmethod
    def _caption(text):
        lab = QLabel(text.upper())
        lab.setObjectName("hint")
        f = lab.font()
        f.setBold(True)
        f.setPointSizeF(8)
        lab.setFont(f)
        return lab

    @staticmethod
    def _grid(cards):
        g = QGridLayout()
        g.setSpacing(2)
        for i, c in enumerate(cards):
            g.addWidget(c, i // 3, i % 3, Qt.AlignLeft)
        g.setColumnStretch(3, 1)
        return g

    def _card(self, preset: Preset) -> ThemeCard:
        c = ThemeCard(preset)
        c.clicked.connect(lambda _=False, pid=preset.id: self.themes.set(mode="preset", preset_id=pid))
        self.cards.append(c)
        return c

    def _mode(self, key):
        if key == "themes":
            if self.themes.mode not in ("preset", "custom"):
                self.themes.set(mode="preset")
        else:
            self.themes.set(mode=key)

    def _open_custom(self):
        self.themes.set(mode="custom")
        dlg = CustomThemeDialog(self.themes.custom, self)
        dlg.picked.connect(lambda p: self.themes.set(mode="custom", custom=p))
        dlg.exec()

    def _sync(self, *_):
        t = self.themes
        mode_key = t.mode if t.mode.startswith("classic") else "themes"
        self.mode_buttons[mode_key].setChecked(True)
        for c in self.cards:
            c.set_active(t.mode == "preset" and c.preset.id == t.preset_id)
        self.custom_card.set_preset(t.custom)
        self.custom_card.set_active(t.mode == "custom")
        self.current.setText(f"Сейчас: {t.theme.name}" + ("  ·  фон чертежа классический" if t.classic_canvas and not t.mode.startswith("classic") else ""))
