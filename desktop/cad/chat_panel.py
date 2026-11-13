"""Вложения в чате ИИ-помощника: поле ввода со вставкой скриншота (Ctrl+V) и перетаскиванием файлов, лента
прикреплённых файлов (миниатюра или значок DOCX, имя, «×»), обработка вложений в отдельном потоке."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QToolButton, QVBoxLayout, QWidget

from . import attachments
from .attachments import AttachError, Attachment

BADGE_COLORS = {"DOCX": "#2b579a", "CSV": "#217346", "JSON": "#b26b00", "TXT": "#5b6470"}
THUMB = 44


def dropped_paths(md) -> list[str]:
    """Локальные файлы из перетаскивания или буфера обмена (неподдерживаемые тоже — load объяснит, почему нет)."""
    if not md.hasUrls():
        return []
    return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and Path(u.toLocalFile()).is_file()]


def pasted_image(md) -> QImage | None:
    """Скриншот из буфера или картинка из браузера. Текст из Word тоже несёт картинку выделения — тогда вставляем
    текст, а не картинку; у картинки из браузера текст — только её адрес."""
    text = md.text().strip() if md.hasText() else ""
    if not md.hasImage() or (text and not re.fullmatch(r"(https?|file|data):\S*", text)):
        return None
    img = md.imageData()
    if isinstance(img, QPixmap):
        img = img.toImage()
    return img if isinstance(img, QImage) and not img.isNull() else None


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


class ChatInput(QPlainTextEdit):
    """Поле запроса: Ctrl+V со скриншотом и перетаскивание файлов прикрепляют их, обычный текст вставляется как текст."""
    filesDropped = Signal(list)
    imagePasted = Signal(QImage)

    def canInsertFromMimeData(self, md):
        return bool(dropped_paths(md) or pasted_image(md) is not None) or super().canInsertFromMimeData(md)

    def insertFromMimeData(self, md):
        paths = dropped_paths(md)
        if paths:
            self.filesDropped.emit(paths)
            return
        img = pasted_image(md)
        if img is not None:
            self.imagePasted.emit(img)
            return
        super().insertFromMimeData(md)


class DropCatcher(QObject):
    """Перетаскивание фото и документов на всю панель чата (историю, кнопки): подсветка и приём."""
    filesDropped = Signal(list)
    imageDropped = Signal(QImage)
    hovering = Signal(bool)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.DragEnter, QEvent.DragMove):
            md = ev.mimeData()
            if dropped_paths(md) or pasted_image(md) is not None:
                ev.acceptProposedAction()
                if t == QEvent.DragEnter:
                    self.hovering.emit(True)
                return True
        elif t == QEvent.DragLeave:
            self.hovering.emit(False)
        elif t == QEvent.Drop:
            self.hovering.emit(False)
            md = ev.mimeData()
            paths = dropped_paths(md)
            img = pasted_image(md)
            if paths or img is not None:
                ev.acceptProposedAction()
                if paths:
                    self.filesDropped.emit(paths)
                else:
                    self.imageDropped.emit(img)
                return True
        return False


def badge_pixmap(text: str, size: int = THUMB) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(BADGE_COLORS.get(text, "#5b6470")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2, 4, size - 4, size - 8), 5, 5)
    f = QFont("Segoe UI")
    f.setPixelSize(max(9, size // (4 if len(text) > 3 else 3)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, text)
    p.end()
    return pm


def thumb_pixmap(att: Attachment, size: int = THUMB) -> QPixmap:
    if att.kind != "image":
        return badge_pixmap(att.badge, size)
    pm = QPixmap()
    pm.loadFromData(att.thumb or att.data)
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pm.isNull() else badge_pixmap("IMG", size)


class AttachmentChip(QFrame):
    removeRequested = Signal()

    def __init__(self, att: Attachment, parent=None):
        super().__init__(parent)
        self.att = att
        self.setObjectName("attachChip")
        self.setFixedSize(172, 54)
        self.setToolTip(f"{att.name}\n{att.caption()}" + (f"\n\n{att.text[:900]}" if att.kind == "image" and att.text else ""))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 2, 4)
        lay.setSpacing(6)
        pic = QLabel()
        pic.setFixedSize(THUMB, THUMB)
        pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(thumb_pixmap(att))
        lay.addWidget(pic)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel()
        name.setText(name.fontMetrics().elidedText(att.name, Qt.ElideMiddle, 92))
        sub = QLabel()
        sub.setObjectName("chipSub")
        sub.setText(sub.fontMetrics().elidedText(att.caption(), Qt.ElideRight, 92))
        col.addWidget(name)
        col.addWidget(sub)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("chipClose")
        self.close_btn.setText("×")
        self.close_btn.setToolTip("Убрать вложение")
        self.close_btn.setAutoRaise(True)
        self.close_btn.clicked.connect(self.removeRequested)
        lay.addWidget(self.close_btn, 0, Qt.AlignTop)


class AttachmentBar(QScrollArea):
    """Лента прикреплённых файлов над полем ввода; пустая — скрыта."""
    removed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("attachBar")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFixedHeight(70)
        self.inner = QWidget()
        self.inner.setObjectName("attachInner")
        self.row = QHBoxLayout(self.inner)
        self.row.setContentsMargins(0, 2, 0, 2)
        self.row.setSpacing(6)
        self.row.addStretch(1)
        self.setWidget(self.inner)
        self.chips: list[AttachmentChip] = []
        self.hide()

    def set_items(self, items: list[Attachment]):
        for c in self.chips:
            self.row.removeWidget(c)
            c.deleteLater()
        self.chips = []
        for i, att in enumerate(items):
            chip = AttachmentChip(att, self.inner)
            chip.removeRequested.connect(lambda i=i: self.removed.emit(i))
            self.row.insertWidget(i, chip)
            self.chips.append(chip)
        self.setVisible(bool(items))

    def sizeHint(self):
        return QSize(300, 70)


class AttachWorker(QThread):
    """Чтение, сжатие и анализ вложений в фоне: фото с телефона и Word с рисунками не подвешивают окно."""
    loaded = Signal(object)          # list[Attachment]
    failed = Signal(str)

    def __init__(self, jobs: list[tuple], parent=None):
        super().__init__(parent)
        self.jobs = list(jobs)       # ("path", путь) или ("png", байты, имя)

    def run(self):
        for job in self.jobs:
            try:
                if job[0] == "path":
                    self.loaded.emit(attachments.load(job[1]))
                else:
                    self.loaded.emit([attachments.image(job[1], job[2])])
            except AttachError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # noqa: BLE001 — сбой разбора одного файла не валит поток и окно
                self.failed.emit(f"«{Path(str(job[-1])).name}»: не удалось обработать ({exc})")
