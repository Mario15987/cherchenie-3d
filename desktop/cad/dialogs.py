"""Диалоги: одна универсальная форма для параметров операций, объектов, рамки и штампа; настройки ИИ.

Все вопросы пользователю идут через ask_form — в автотестах Ask.AUTO = True, и форма сразу возвращает значения
по умолчанию (так тест прогоняет каждую кнопку без всплывающих окон).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QSizePolicy, QSpinBox,
)

from . import ai


class Ask:
    AUTO = False          # автотесты: не показывать окна, брать значения по умолчанию
    answers: dict = {}    # автотесты: подменить ответы по ключу поля


def ask_form(parent, title: str, fields: list[tuple], note: str = "", focus: str | None = None) -> dict | None:
    """fields: (ключ, подпись, вид, значение, доп.). Вид: float (мин, макс), int (мин, макс), choice [(значение, подпись)],
    bool, text, combo_text [варианты]. Возвращает словарь значений или None, если отменили."""
    if Ask.AUTO:
        Ask.answers.setdefault("_forms", []).append(title)
        return {k: Ask.answers.get(k, v) for k, _, _, v, *_ in fields}
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(380)
    form = QFormLayout(dlg)
    getters = {}
    first = None
    for key, label, kind, value, *extra in fields:
        if kind == "float":
            w = QDoubleSpinBox()
            lo, hi = extra[0] if extra else (-1e6, 1e6)
            w.setRange(lo, hi)
            w.setDecimals(3)
            w.setValue(float(value))
            getters[key] = w.value
        elif kind == "int":
            w = QSpinBox()
            lo, hi = extra[0] if extra else (0, 10000)
            w.setRange(lo, hi)
            w.setValue(int(value))
            getters[key] = w.value
        elif kind == "choice":
            w = QComboBox()
            for v, lab in extra[0]:
                w.addItem(lab, v)
            w.setCurrentIndex(max(0, w.findData(value)))
            getters[key] = w.currentData
        elif kind == "combo_text":
            w = QComboBox()
            w.setEditable(True)
            w.addItems(extra[0])
            w.setCurrentText(str(value))
            getters[key] = lambda w=w: w.currentText().strip()
        elif kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            getters[key] = w.isChecked
        else:
            w = QLineEdit(str(value))
            getters[key] = lambda w=w: w.text().strip()
        form.addRow(label, w)
        if key == focus or first is None:
            first = w
    if note:
        lab = QLabel(note)
        lab.setWordWrap(True)
        lab.setObjectName("hint")
        form.addRow(lab)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    if first is not None:
        first.setFocus()
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: g() for k, g in getters.items()}


class QuickEdit(QDialog):
    """Быстрый ввод у курсора, как по двойному щелчку в КОМПАС: первое поле в фокусе и выделено — сразу печатайте
    число и Enter. Esc или щелчок мимо — отмена. link=(a, b, k): поля связаны, b = a·k (Ø и R)."""

    def __init__(self, parent, title: str, fields: list[tuple], link: tuple | None = None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("quickEdit")
        self.spins: dict[str, QDoubleSpinBox] = {}
        form = QFormLayout(self)
        form.setContentsMargins(10, 8, 10, 8)
        cap = QLabel(f"<b>{title}</b>")
        form.addRow(cap)
        for key, label, value, lo, hi in fields:
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(2)
            s.setValue(value)
            s.setMinimumWidth(110)
            s.lineEdit().returnPressed.connect(self.accept)
            self.spins[key] = s
            form.addRow(label, s)
        hint = QLabel("Enter — применить, Esc — отмена")
        hint.setObjectName("hint")
        form.addRow(hint)
        if link:
            a, b, k = link
            self.spins[a].valueChanged.connect(lambda v: self._set(b, v * k))
            self.spins[b].valueChanged.connect(lambda v: self._set(a, v / k))
        self.first = self.spins[fields[0][0]]

    def _set(self, key, value):
        s = self.spins[key]
        if abs(s.value() - value) > 1e-9:
            s.blockSignals(True)
            s.setValue(value)
            s.blockSignals(False)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.first.setFocus()
        self.first.selectAll()

    def values(self) -> dict:
        return {k: s.value() for k, s in self.spins.items()}

    def place_near(self, pos: QPoint):
        """У курсора, но целиком на экране."""
        self.adjustSize()
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        r = scr.availableGeometry()
        x = min(max(pos.x() + 14, r.left()), r.right() - self.width())
        y = min(max(pos.y() + 14, r.top()), r.bottom() - self.height())
        self.move(x, y)


def quick_edit(parent, title: str, fields: list[tuple], link: tuple | None = None) -> dict | None:
    """fields: (ключ, подпись, значение, мин, макс). Возвращает значения или None. В автотестах — как ask_form."""
    if Ask.AUTO:
        Ask.answers.setdefault("_forms", []).append(title)
        return {k: Ask.answers.get(k, v) for k, _, v, *_ in fields}
    dlg = QuickEdit(parent, title, fields, link)
    dlg.place_near(QCursor.pos())
    return dlg.values() if dlg.exec() == QDialog.Accepted else None


def warn(parent, title, text):
    if Ask.AUTO:
        Ask.answers.setdefault("_warnings", []).append(text)
        return
    QMessageBox.warning(parent, title, text)


class AISettingsDialog(QDialog):
    """Ключ, тип API, модель, Base URL. Всё сохраняется в config.json рядом с программой."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки ИИ")
        self.setMinimumWidth(520)
        self.provider = QComboBox()
        for k, v in ai.PROVIDERS.items():
            self.provider.addItem(v, k)
        self.key = QLineEdit(cfg.get("api_key", ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Вставьте свой API-ключ")
        show = QCheckBox("показать")
        show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(show)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.base = QLineEdit(cfg.get("base_url", ""))
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("hint")
        form = QFormLayout(self)
        form.addRow("Тип API", self.provider)
        form.addRow("API Key", key_row)
        form.addRow("Модель", self.model)
        self.vision_note = QLabel(ai.hint_html(ai.VISION_MEMO))
        self.vision_note.setObjectName("visionNote")
        self.vision_note.setTextFormat(Qt.RichText)
        self.vision_note.setWordWrap(True)
        self.vision_note.setMinimumWidth(380)    # ширина известна заранее — высота по тексту, без пустого места
        self.vision_note.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.vision_note.setToolTip(ai.VISION_HINT.replace("`", ""))
        form.addRow("", self.vision_note)
        form.addRow("Base URL", self.base)
        form.addRow(self.note)
        path = QLabel(f"Файл настроек: {ai.config_path()}\nКлюч хранится в нём открытым текстом — не передавайте этот файл другим.")
        path.setWordWrap(True)
        path.setObjectName("hint")
        form.addRow(path)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.provider.currentIndexChanged.connect(self._on_provider)
        self.provider.setCurrentIndex(max(0, self.provider.findData(cfg.get("provider", "anthropic"))))
        self._on_provider()
        if cfg.get("model"):
            self.model.setCurrentText(cfg["model"])
        self.result_cfg = dict(cfg)

    def _on_provider(self):
        p = self.provider.currentData()
        cur = self.model.currentText()
        self.model.clear()
        if p == "anthropic":
            self.model.addItems(ai.CLAUDE_MODELS)
            self.note.setText("Claude вызывается через официальный SDK Anthropic. По умолчанию — claude-opus-5-5. "
                              "Фото и сканы Claude читает сам.")
        else:
            self.note.setText({"openai": "Любой сервер с API /chat/completions. Впишите идентификатор модели вашего провайдера.",
                               "openrouter": "Модель в формате OpenRouter, например «провайдер/модель».",
                               "gemini": "Впишите идентификатор модели Gemini из консоли Google AI Studio.",
                               "groq": "OpenAI-совместимый API Groq. Для фото выберите модель с поддержкой изображений; "
                                       "в один запрос уходит не больше 3 картинок.",
                               "custom": "Свой OpenAI-совместимый сервер (например, локальный). Ключ можно оставить пустым."}[p])
        if cur and (p == "anthropic") == cur.startswith("claude-"):
            self.model.setCurrentText(cur)
        self.base.setPlaceholderText(ai.DEFAULT_BASE[p] or "не нужен")
        self.base.setEnabled(p != "anthropic")

    def _accept(self):
        self.result_cfg = {"provider": self.provider.currentData(), "api_key": self.key.text().strip(),
                           "model": self.model.currentText().strip(), "base_url": self.base.text().strip()}
        self.accept()
