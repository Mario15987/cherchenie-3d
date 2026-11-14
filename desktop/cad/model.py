"""Модель проекта. Формат файла .k3d — JSON.

- entities — текущий (свободный) эскиз на плоскости XY: из него строятся операции;
- features — дерево построения; у каждой операции свой эскиз (feature["sketch"]), как в КОМПАС:
  эскиз «уходит» в операцию, а правка его размеров перестраивает модель;
- drawing — лист чертежа: рамка со штампом, виды, размеры, штриховки, свои линии.

Координаты в миллиметрах, ось Y вверх (как на чертеже).
"""
from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import dataclass, field

SCHEMA = "k3d/2"

# Типы линий по ГОСТ 2.303-68.
# Девять типов: шесть первых — с первой версии файла, три последних добавлены позже (порядок не менять).
STYLES = ("main", "thin", "hidden", "axis", "fold", "wavy", "axis_thick", "open", "zigzag")
STYLE_LABEL = {
    "main": "Основная толстая", "thin": "Тонкая", "hidden": "Штриховая (невидимый контур)",
    "axis": "Штрихпунктирная (осевая)", "fold": "Штрихпунктирная с двумя точками (сгиб)", "wavy": "Волнистая (обрыв)",
    "axis_thick": "Штрихпунктирная утолщённая", "open": "Разомкнутая (линия сечения)", "zigzag": "Тонкая с изломами (длинный обрыв)",
}
CURVES = ("line", "circle", "arc")
DIMS = ("dim", "diadim", "raddim", "angdim", "leader", "rough")

# Форматы по ГОСТ 2.301: (ширина, высота) в книжной ориентации.
FORMATS = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0), "A1": (594.0, 841.0), "A0": (841.0, 1189.0),
           # кратные (дополнительные) форматы: короткая сторона основного × кратность
           "A4x3": (297.0, 630.0), "A4x4": (297.0, 841.0), "A3x3": (420.0, 891.0), "A3x4": (420.0, 1189.0),
           "A2x3": (594.0, 1261.0), "A1x3": (841.0, 1783.0), "A0x2": (1189.0, 1682.0)}
FORMAT_LABEL = {k: k.replace("A", "А").replace("x", "×") for k in FORMATS}


def sheet_size(fmt: str, orient: str) -> tuple[float, float]:
    w, h = FORMATS[fmt]
    return (h, w) if orient == "landscape" else (w, h)


# Формат полотна чертежа: бесконечный фрагмент или лист с рамкой. Ключ -> (подпись, формат, ориентация).
CANVAS_MODES = {
    "fragment": ("Бесконечное полотно (Фрагмент)", None, None),
    "A4P": ("Лист А4 книжная (210 × 297 мм, ГОСТ)", "A4", "portrait"),
    "A4L": ("Лист А4 альбомная (297 × 210 мм, ГОСТ)", "A4", "landscape"),
    "A3L": ("Лист А3 альбомная (420 × 297 мм, ГОСТ)", "A3", "landscape"),
    "A3P": ("Лист А3 книжная (297 × 420 мм, ГОСТ)", "A3", "portrait"),
    "A2L": ("Лист А2 альбомная (594 × 420 мм, ГОСТ)", "A2", "landscape"),
    "A2P": ("Лист А2 книжная (420 × 594 мм, ГОСТ)", "A2", "portrait"),
    "A1L": ("Лист А1 альбомная (841 × 594 мм, ГОСТ)", "A1", "landscape"),
    "A1P": ("Лист А1 книжная (594 × 841 мм, ГОСТ)", "A1", "portrait"),
    "A0L": ("Лист А0 альбомная (1189 × 841 мм, ГОСТ)", "A0", "landscape"),
    "A0P": ("Лист А0 книжная (841 × 1189 мм, ГОСТ)", "A0", "portrait"),
    "A4x3L": ("Лист А4×3 (630 × 297 мм, кратный)", "A4x3", "landscape"),
    "A4x4L": ("Лист А4×4 (841 × 297 мм, кратный)", "A4x4", "landscape"),
    "A3x3L": ("Лист А3×3 (891 × 420 мм, кратный)", "A3x3", "landscape"),
    "A3x4L": ("Лист А3×4 (1189 × 420 мм, кратный)", "A3x4", "landscape"),
    "A2x3L": ("Лист А2×3 (1261 × 594 мм, кратный)", "A2x3", "landscape"),
}


def canvas_key(fmt: str, orient: str) -> str:
    return f"{fmt}{'L' if orient == 'landscape' else 'P'}"


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def _num(v, name: str) -> float:
    x = float(v)
    if not math.isfinite(x):
        raise ValueError(f"{name}: не число")
    return x


def _style(style):
    return style if style in STYLES else "main"


def make_line(x1, y1, x2, y2, style="main") -> dict:
    return {"id": new_id(), "type": "line", "style": _style(style),
            "x1": _num(x1, "x1"), "y1": _num(y1, "y1"), "x2": _num(x2, "x2"), "y2": _num(y2, "y2")}


def make_circle(cx, cy, r, style="main") -> dict:
    r = _num(r, "r")
    if r <= 0:
        raise ValueError("радиус должен быть больше нуля")
    return {"id": new_id(), "type": "circle", "style": _style(style), "cx": _num(cx, "cx"), "cy": _num(cy, "cy"), "r": r}


def make_arc(cx, cy, r, a0, a1, style="main") -> dict:
    """Дуга против часовой стрелки от угла a0 до a1, градусы."""
    r = _num(r, "r")
    if r <= 0:
        raise ValueError("радиус должен быть больше нуля")
    return {"id": new_id(), "type": "arc", "style": _style(style), "cx": _num(cx, "cx"), "cy": _num(cy, "cy"), "r": r,
            "a0": _num(a0, "a0") % 360.0, "a1": _num(a1, "a1") % 360.0}


def make_rect(x, y, w, h, style="main") -> list[dict]:
    x, y, w, h = (_num(v, n) for v, n in ((x, "x"), (y, "y"), (w, "w"), (h, "h")))
    if w == 0 or h == 0:
        raise ValueError("у прямоугольника нулевая сторона")
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    rid = new_id()   # прямоугольник — один объект, как в КОМПАС: выделяется и правится целиком
    return [{**make_line(*pts[i], *pts[(i + 1) % 4], style=style), "rect": rid} for i in range(4)]


# ---------------------------------------------------------------- размеры и обозначения
def make_dim(x1, y1, x2, y2, off=8.0, kind="aligned") -> dict:
    """Линейный размер. kind: aligned (параллельный), horizontal, vertical. off — вынос размерной линии, мм."""
    if kind not in ("aligned", "horizontal", "vertical"):
        raise ValueError("вид линейного размера: aligned, horizontal или vertical")
    return {"id": new_id(), "type": "dim", "style": "thin", "kind": kind, "x1": _num(x1, "x1"), "y1": _num(y1, "y1"),
            "x2": _num(x2, "x2"), "y2": _num(y2, "y2"), "off": _num(off, "off"), "tol": "", "text": ""}


def make_diadim(cx, cy, r, ang=45.0) -> dict:
    return {"id": new_id(), "type": "diadim", "style": "thin", "cx": _num(cx, "cx"), "cy": _num(cy, "cy"),
            "r": _num(r, "r"), "ang": _num(ang, "ang"), "tol": "", "text": ""}


def make_raddim(cx, cy, r, ang=45.0) -> dict:
    return {"id": new_id(), "type": "raddim", "style": "thin", "cx": _num(cx, "cx"), "cy": _num(cy, "cy"),
            "r": _num(r, "r"), "ang": _num(ang, "ang"), "tol": "", "text": ""}


def make_angdim(cx, cy, a1, a2, rad=20.0) -> dict:
    """Угловой размер между лучами из (cx, cy) под углами a1 и a2 (против часовой от a1 к a2)."""
    return {"id": new_id(), "type": "angdim", "style": "thin", "cx": _num(cx, "cx"), "cy": _num(cy, "cy"),
            "a1": _num(a1, "a1") % 360, "a2": _num(a2, "a2") % 360, "rad": _num(rad, "rad"), "tol": "", "text": ""}


def make_leader(x1, y1, x2, y2, text) -> dict:
    """Линия-выноска: стрелка в (x1, y1), излом в (x2, y2), дальше полка с текстом."""
    return {"id": new_id(), "type": "leader", "style": "thin", "x1": _num(x1, "x1"), "y1": _num(y1, "y1"),
            "x2": _num(x2, "x2"), "y2": _num(y2, "y2"), "text": str(text)}


def make_rough(x, y, value="3,2", param="Ra") -> dict:
    """Шероховатость по ГОСТ 2.309: знак с вершиной в (x, y)."""
    if param not in ("Ra", "Rz"):
        raise ValueError("параметр шероховатости: Ra или Rz")
    return {"id": new_id(), "type": "rough", "style": "thin", "x": _num(x, "x"), "y": _num(y, "y"), "value": str(value), "param": param}


TEXT_ALIGN = ("left", "center", "right")


def make_text(x, y, text, h=3.5, ang=0.0, align="left") -> dict:
    """Надпись шрифтом ГОСТ 2.304: (x, y) — точка на линии основания, h — высота прописных, мм."""
    h = _num(h, "h")
    if h <= 0:
        raise ValueError("высота шрифта должна быть больше нуля")
    return {"id": new_id(), "type": "text", "style": "thin", "x": _num(x, "x"), "y": _num(y, "y"), "h": h,
            "ang": _num(ang, "ang"), "align": align if align in TEXT_ALIGN else "left", "text": str(text)}


HATCH_PATTERNS = {"metal": "Металл", "nonmetal": "Неметалл", "concrete": "Бетон", "glass": "Стекло",
                  "wood": "Дерево", "liquid": "Жидкость", "ground": "Грунт"}


def make_hatch(boundary, pattern="metal", step=2.0, angle=45.0) -> dict:
    if pattern not in HATCH_PATTERNS:
        raise ValueError(f"штриховка: {', '.join(HATCH_PATTERNS)}")
    step = _num(step, "step")
    if step <= 0.1:
        raise ValueError("шаг штриховки должен быть больше 0,1 мм")
    return {"id": new_id(), "type": "hatch", "style": "thin", "boundary": [[[float(x), float(y)] for x, y in poly] for poly in boundary],
            "pattern": pattern, "step": step, "angle": _num(angle, "angle")}


# ---------------------------------------------------------------- дуги
def arc_points(e: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    a0, a1 = math.radians(e["a0"]), math.radians(e["a1"])
    return ((e["cx"] + e["r"] * math.cos(a0), e["cy"] + e["r"] * math.sin(a0)),
            (e["cx"] + e["r"] * math.cos(a1), e["cy"] + e["r"] * math.sin(a1)))


def arc_sweep(e: dict) -> float:
    s = (e["a1"] - e["a0"]) % 360.0
    return s if s > 1e-9 else 360.0


def entity_label(e: dict) -> str:
    t = e["type"]
    if t == "line":
        length = math.hypot(e["x2"] - e["x1"], e["y2"] - e["y1"])
        return f"{'Осевая' if e['style'] == 'axis' else 'Отрезок'} {length:.2f}"
    if t == "circle":
        return f"Окружность Ø{2 * e['r']:.2f}"
    if t == "arc":
        return f"Дуга R{e['r']:.2f}"
    if t == "dim":
        return f"Размер {math.hypot(e['x2'] - e['x1'], e['y2'] - e['y1']):.2f}"
    if t == "diadim":
        return f"Размер Ø{2 * e['r']:.2f}"
    if t == "raddim":
        return f"Размер R{e['r']:.2f}"
    if t == "angdim":
        return f"Угловой размер {(e['a2'] - e['a1']) % 360:.1f}°"
    if t == "leader":
        return f"Выноска «{e['text']}»"
    if t == "rough":
        return f"Шероховатость {e['param']} {e['value']}"
    if t == "hatch":
        return f"Штриховка ({HATCH_PATTERNS[e['pattern']].lower()})"
    if t == "text":
        return f"Надпись «{e['text'][:40]}»"
    return t


FEATURE_LABEL = {"extrude": "Выдавливание", "cut": "Вырез", "revolve": "Вращение", "shell": "Оболочка",
                 "fillet3d": "Скругление рёбер", "chamfer3d": "Фаска рёбер"}

STAMP_ROLES = ("Разраб.", "Пров.", "Т. контр.", "Н. контр.", "Утв.")


def default_frame() -> dict:
    return {"format": "A3", "orient": "landscape", "x": 0.0, "y": 0.0, "scale": "1:1", "mass": "", "litera": "",
            "sheet": "1", "sheets": "1", "org": "Черчение 3D", "people": {r: "" for r in STAMP_ROLES}, "form": "1"}


def default_eskd() -> dict:
    """Настройки оформления по ЕСКД и данные документов, которые строятся из них (ТТ, спецификация, текст)."""
    return {"s": 0.5,                 # толщина основной линии s, мм (ГОСТ 2.303: 0,5…1,4)
            "font": "B", "slant": True,   # шрифт ГОСТ 2.304: тип А или Б, с наклоном 75° или прямой
            "doc": "part",            # вид документа со стартового экрана
            "tech": [],               # технические требования (ГОСТ 2.316) — пункты
            "spec": [],               # строки спецификации (ГОСТ 2.106)
            "text": "",               # текст пояснительной записки (ГОСТ 2.105)
            "scheme": "",             # шифр схемы по ГОСТ 2.701 (Э3, Г1…)
            "pages": {}}              # прямоугольники листов-продолжений (спецификация, записка) — под них кладётся бумага


@dataclass
class Project:
    name: str = "Деталь"
    designation: str = ""
    material: str = ""
    entities: list[dict] = field(default_factory=list)   # свободный эскиз
    features: list[dict] = field(default_factory=list)   # дерево построения
    drawing: list[dict] = field(default_factory=list)    # лист чертежа
    frame: dict | None = None                            # рамка и штамп (на листе чертежа)
    canvas: str = "fragment"                             # fragment — бесконечное полотно, sheet — лист с рамкой
    eskd: dict = field(default_factory=default_eskd)     # оформление по ЕСКД, ТТ, спецификация, текст документа

    # ---------- сериализация ----------
    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "name": self.name, "designation": self.designation, "material": self.material,
                "entities": self.entities, "features": self.features, "drawing": self.drawing, "frame": self.frame,
                "canvas": self.canvas, "eskd": self.eskd}

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        schema = d.get("schema")
        if schema not in ("k3d/1", SCHEMA):
            raise ValueError("Это не проект .k3d или файл другой версии")
        p = cls(name=d.get("name", "Деталь"), designation=d.get("designation", ""), material=d.get("material", ""),
                entities=list(d.get("entities", [])), features=list(d.get("features", [])),
                drawing=list(d.get("drawing", [])), frame=d.get("frame"),
                canvas=d.get("canvas") or ("sheet" if d.get("frame") else "fragment"),
                eskd={**default_eskd(), **(d.get("eskd") or {})})
        if p.canvas not in ("fragment", "sheet") or (p.canvas == "sheet" and not p.frame):
            p.canvas = "fragment"
        for e in p.all_entities():
            e.setdefault("id", new_id())
            e.setdefault("style", "thin" if e.get("type") in DIMS + ("hatch",) else "main")
            if e.get("type") == "dim":
                e.setdefault("kind", "aligned")
            if e.get("type") in DIMS:
                e.setdefault("tol", "")
                e.setdefault("text", "") if e["type"] != "leader" else None
        if schema == "k3d/1":
            # В версии 1 рамка и размеры жили в эскизе, у операций был только готовый профиль.
            p.drawing = [e for e in p.entities if e.get("type") in DIMS]
            p.entities = [e for e in p.entities if e.get("type") not in DIMS]
            for f in p.features:
                f.setdefault("sketch", [])
                if f["type"] == "cut":
                    f.update(type="extrude", op="cut")
        if p.frame:
            base = default_frame()
            base.update(p.frame)
            base["people"] = {**default_frame()["people"], **(p.frame.get("people") or {})}
            if p.frame.get("format") in ("A3",) and "orient" not in p.frame:
                base["orient"] = "landscape"
            p.frame = base
        for f in p.features:
            f.setdefault("sketch", [])
            f.setdefault("op", "add")
        return p

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def snapshot(self) -> dict:
        return copy.deepcopy(self.to_dict())

    def restore(self, snap: dict) -> None:
        other = Project.from_dict(copy.deepcopy(snap))
        self.__dict__.update(other.__dict__)

    # ---------- доступ ----------
    def sheet(self) -> dict | None:
        """Рамка листа, если полотно — лист. На бесконечном полотне рамка не видна, но её данные (штамп) хранятся."""
        return self.frame if self.canvas == "sheet" else None

    def canvas_mode(self) -> str:
        return canvas_key(self.frame["format"], self.frame["orient"]) if self.sheet() else "fragment"

    def all_entities(self):
        yield from self.entities
        yield from self.drawing
        for f in self.features:
            yield from f.get("sketch", [])

    def container_of(self, eid: str) -> list[dict] | None:
        for lst in (self.entities, self.drawing, *[f.get("sketch", []) for f in self.features]):
            if any(e["id"] == eid for e in lst):
                return lst
        return None

    def find(self, eid: str) -> dict | None:
        return next((e for e in self.all_entities() if e["id"] == eid), None)

    def feature(self, fid: str) -> dict | None:
        return next((f for f in self.features if f["id"] == fid), None)

    def remove(self, ids) -> int:
        ids, n = set(ids), 0
        for lst in (self.entities, self.drawing, *[f.get("sketch", []) for f in self.features]):
            before = len(lst)
            lst[:] = [e for e in lst if e["id"] not in ids]
            n += before - len(lst)
        return n

    @staticmethod
    def profile_of(entities: list[dict]) -> list[dict]:
        """Что участвует в контурах для 3D: основные линии, дуги, окружности."""
        return [e for e in entities if e.get("style") == "main" and e["type"] in CURVES]

    def profile_entities(self) -> list[dict]:
        return self.profile_of(self.entities)


class History:
    """Отмена и повтор на снимках проекта. Проекты маленькие — снимок целиком дешевле, чем разностные команды."""

    def __init__(self, project: Project, limit: int = 100):
        self.project = project
        self.limit = limit
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []

    def push(self) -> None:
        self.undo_stack.append(self.project.snapshot())
        self.undo_stack = self.undo_stack[-self.limit:]
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.project.snapshot())
        self.project.restore(self.undo_stack.pop())
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.project.snapshot())
        self.project.restore(self.redo_stack.pop())
        return True

    def reset(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()
