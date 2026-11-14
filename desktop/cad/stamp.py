"""Рамка и основная надпись по ГОСТ 2.104-2006, форматы по ГОСТ 2.301. Три формы основной надписи:
форма 1 (185 × 55 мм) — первый лист чертежей и схем; форма 2 (185 × 40 мм) — первый лист текстовых документов
и спецификаций; форма 2а (185 × 15 мм) — последующие листы. Форма хранится в frame["form"]: "1", "2", "2a".

Своё построение по размерам стандарта (файлы оформления других САПР не используются). Каждая графа знает своё
поле — так двойной щелчок по штампу открывает редактирование нужной графы.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import STAMP_ROLES, sheet_size

W, H = 185.0, 55.0          # форма 1 — она же по умолчанию
FORMS = {"1": ("Форма 1 — чертежи и схемы, первый лист", 55.0),
         "2": ("Форма 2 — текстовые документы и спецификации, первый лист", 40.0),
         "2a": ("Форма 2а — последующие листы", 15.0)}


def form_of(frame: dict | None) -> str:
    f = str((frame or {}).get("form", "1")).lower().replace("а", "a")   # кириллическая «а» в «2а» — тоже годится
    return f if f in FORMS else "1"


def stamp_size(frame: dict | None) -> tuple[float, float]:
    """Ширина и высота основной надписи текущей формы, мм."""
    return W, FORMS[form_of(frame)][1]


@dataclass
class Cell:
    x: float
    y: float
    w: float
    h: float
    field: str | None = None     # какое поле редактирует графа
    label: str = ""              # постоянная надпись графы
    text_h: float = 3.5


def frame_rect(frame: dict) -> tuple[float, float, float, float]:
    """Внутренняя рамка: поле 20 мм слева под подшивку, 5 мм с остальных сторон."""
    w, h = sheet_size(frame.get("format", "A3"), frame.get("orient", "landscape"))
    ox, oy = frame.get("x", 0.0), frame.get("y", 0.0)
    return ox + 20, oy + 5, w - 25, h - 10


def _changes(x0, y_top, rows: int) -> list[Cell]:
    """Левая часть 65 мм: строки изменений сверху вниз, последняя из rows — шапка «Изм. Лист № докум. Подп. Дата»."""
    cols = [0, 7, 17, 40, 55, 65]
    out = []
    for row in range(rows):
        y = y_top - 5 * (row + 1)
        for i in range(5):
            label = ("Изм.", "Лист", "№ докум.", "Подп.", "Дата")[i] if row == rows - 1 else ""
            out.append(Cell(x0 + cols[i], y, cols[i + 1] - cols[i], 5, None, label, 2.5))
    return out


def _signers(x0, y0) -> list[Cell]:
    """Пять строк подписей высотой 25 мм от y0: Разраб., Пров., Т. контр., Н. контр., Утв."""
    out = []
    for k, role in enumerate(STAMP_ROLES):
        y = y0 + 25 - 5 * (k + 1)
        out.append(Cell(x0, y, 17, 5, None, role, 2.5))
        out.append(Cell(x0 + 17, y, 23, 5, f"people.{role}", "", 2.5))
        out += [Cell(x0 + 40, y, 15, 5), Cell(x0 + 55, y, 10, 5)]
    return out


def stamp_cells(frame: dict) -> list[Cell]:
    fx, fy, fw, _ = frame_rect(frame)
    x0, y0 = fx + fw - W, fy
    form = form_of(frame)
    if form == "2":     # 185 × 40: текстовые документы и спецификации, первый лист
        r = x0 + 65
        return _changes(x0, y0 + 40, 3) + _signers(x0, y0) + [
            Cell(r, y0 + 25, 120, 15, "designation", "", 7.0),         # графа 2
            Cell(r, y0, 70, 25, "name", "", 5.0),                      # графа 1
            Cell(r + 70, y0 + 20, 15, 5, None, "Лит.", 2.5),
            Cell(r + 85, y0 + 20, 15, 5, None, "Лист", 2.5),
            Cell(r + 100, y0 + 20, 20, 5, None, "Листов", 2.5),
            Cell(r + 70, y0 + 15, 5, 5, "litera", "", 2.5), Cell(r + 75, y0 + 15, 5, 5), Cell(r + 80, y0 + 15, 5, 5),
            Cell(r + 85, y0 + 15, 15, 5, "sheet", "", 3.5),
            Cell(r + 100, y0 + 15, 20, 5, "sheets", "", 3.5),
            Cell(r + 70, y0, 50, 15, "org", "", 3.5),                  # графа 9
        ]
    if form == "2a":    # 185 × 15: последующие листы
        return _changes(x0, y0 + 15, 3) + [
            Cell(x0 + 65, y0, 110, 15, "designation", "", 7.0),
            Cell(x0 + 175, y0 + 8, 10, 7, None, "Лист", 2.5),
            Cell(x0 + 175, y0, 10, 8, "sheet", "", 3.5),
        ]
    cells: list[Cell] = []
    # Левая часть 65 мм: графы 7, 10, 23, 15, 10 мм; 11 строк по 5 мм.
    cols = [0, 7, 17, 40, 55, 65]
    for row in range(5):  # строки изменений (верх) и шапка «Изм. Лист № докум. Подп. Дата»
        y = y0 + 55 - 5 * (row + 1)
        for i in range(5):
            label = ("Изм.", "Лист", "№ докум.", "Подп.", "Дата")[i] if row == 4 else ""
            cells.append(Cell(x0 + cols[i], y, cols[i + 1] - cols[i], 5, None, label, 2.5))
    for k, role in enumerate(STAMP_ROLES):  # Разраб., Пров., Т. контр., Н. контр., Утв.
        y = y0 + 30 - 5 * (k + 1) - (5 if k >= 3 else 0)  # Разраб. 25–30 … Т. контр. 15–20, пусто, Н. контр. 5–10, Утв. 0–5
        cells.append(Cell(x0, y, 17, 5, None, role, 2.5))
        cells.append(Cell(x0 + 17, y, 23, 5, f"people.{role}", "", 2.5))
        cells += [Cell(x0 + 40, y, 15, 5), Cell(x0 + 55, y, 10, 5)]
    cells.append(Cell(x0, y0 + 10, 17, 5))  # пустая строка между Т. контр. и Н. контр.
    cells += [Cell(x0 + 17, y0 + 10, 23, 5), Cell(x0 + 40, y0 + 10, 15, 5), Cell(x0 + 55, y0 + 10, 10, 5)]
    # Правая часть 120 мм.
    r = x0 + 65
    cells += [
        Cell(r, y0 + 40, 120, 15, "designation", "", 7.0),          # графа 2 — обозначение
        Cell(r, y0 + 15, 70, 25, "name", "", 5.0),                  # графа 1 — наименование
        Cell(r, y0, 70, 15, "material", "", 3.5),                   # графа 3 — материал
        Cell(r + 70, y0 + 35, 15, 5, None, "Лит.", 2.5),
        Cell(r + 85, y0 + 35, 17, 5, None, "Масса", 2.5),
        Cell(r + 102, y0 + 35, 18, 5, None, "Масштаб", 2.5),
        Cell(r + 70, y0 + 20, 5, 15, "litera", "", 3.5),
        Cell(r + 75, y0 + 20, 5, 15), Cell(r + 80, y0 + 20, 5, 15),
        Cell(r + 85, y0 + 20, 17, 15, "mass", "", 3.5),
        Cell(r + 102, y0 + 20, 18, 15, "scale", "", 3.5),
        Cell(r + 70, y0 + 15, 20, 5, "sheet", "Лист", 2.5),
        Cell(r + 90, y0 + 15, 30, 5, "sheets", "Листов", 2.5),
        Cell(r + 70, y0, 50, 15, "org", "", 3.5),                   # графа 9 — организация
    ]
    return cells


def field_value(cell: Cell, frame: dict, project) -> str:
    f = cell.field
    if not f:
        return ""
    if f.startswith("people."):
        return (frame.get("people") or {}).get(f.split(".", 1)[1], "")
    if f in ("name", "designation", "material"):
        return getattr(project, f) or ""
    return str(frame.get(f, ""))


def frame_geometry(frame: dict, project) -> tuple[list[tuple], list[tuple]]:
    """Линии (x1, y1, x2, y2, 'main'|'thin') и надписи (x, y, высота, текст, выравнивание)."""
    w, h = sheet_size(frame.get("format", "A3"), frame.get("orient", "landscape"))
    ox, oy = frame.get("x", 0.0), frame.get("y", 0.0)
    lines, texts = [], []

    def rect(x, y, rw, rh, kind):
        lines.extend([(x, y, x + rw, y, kind), (x + rw, y, x + rw, y + rh, kind), (x + rw, y + rh, x, y + rh, kind), (x, y + rh, x, y, kind)])

    rect(ox, oy, w, h, "thin")
    fx, fy, fw, fh = frame_rect(frame)
    rect(fx, fy, fw, fh, "main")
    rect(fx + fw - W, fy, *stamp_size(frame), "main")
    for c in stamp_cells(frame):
        kind = "main" if c.h >= 15 or c.w >= 50 else "thin"
        rect(c.x, c.y, c.w, c.h, kind)
        if c.label:
            ty = c.y + c.h - c.text_h - 0.8 if c.field else c.y + (c.h - c.text_h) / 2
            texts.append((c.x + (1.0 if c.w > 12 else c.w / 2), ty, c.text_h, c.label, "left" if c.w > 12 else "center"))
        v = field_value(c, frame, project)
        if v:
            # длинное значение (наименование) уменьшаем, чтобы осталось в графе; ширина курсива ≈ 0,8 высоты на знак
            th = max(1.8, min(c.text_h, (c.w - 3) / (0.8 * len(v))))
            if c.label:  # «Лист 1», «Листов 1» — значение после подписи
                texts.append((c.x + c.w - 1.5, c.y + (c.h - th) / 2, th, v, "right"))
            else:
                texts.append((c.x + c.w / 2 if c.w > 23 else c.x + 1.0, c.y + (c.h - th) / 2, th, v, "center" if c.w > 23 else "left"))
    return lines, texts


def hit_cell(frame: dict, x: float, y: float) -> Cell | None:
    for c in stamp_cells(frame):
        if c.x <= x <= c.x + c.w and c.y <= y <= c.y + c.h:
            return c
    return None
