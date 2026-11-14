"""ЕСКД: справочник стандартов, масштабы ГОСТ 2.302, спецификация ГОСТ 2.106, текстовый документ ГОСТ 2.105,
технические требования ГОСТ 2.316, шифры схем ГОСТ 2.701 и нормоконтроль чертежа.

Справочник — краткие пересказы своими словами и таблицы чисел из стандартов; тексты стандартов сюда не копируются.
Всё, что модуль кладёт на лист (таблица спецификации, пункты ТТ, текст записки), помечается полем gen и при
повторном построении заменяется, а не дублируется. Без Qt — проверяется в тестах ядра.
"""
from __future__ import annotations

from . import library
from .linestyles import S_MAX, S_MIN
from .model import FORMATS, HATCH_PATTERNS, STYLE_LABEL, STYLES, default_frame, make_line, make_text, sheet_size
from .stamp import FORMS, form_of, frame_geometry, frame_rect, stamp_size

# ---------------------------------------------------------------- ГОСТ 2.302: масштабы
GOST_SCALES = ["1:100", "1:50", "1:20", "1:10", "1:5", "1:4", "1:2,5", "1:2", "1:1", "2:1", "2,5:1", "4:1", "5:1", "10:1"]
FONT_SIZES = [2.5, 3.5, 5.0, 7.0, 10.0, 14.0, 20.0]      # ГОСТ 2.304: высота прописных букв h, мм


def scale_factor(label: str) -> float:
    """«1:2,5» → 0,4 (во сколько раз изображение на листе больше натуры). Не масштаб — ValueError."""
    try:
        a, b = (float(x.replace(",", ".")) for x in str(label).replace(" ", "").split(":"))
        if a <= 0 or b <= 0:
            raise ValueError
        return a / b
    except (ValueError, AttributeError):
        raise ValueError(f"масштаб «{label}»: нужен вид 1:2 или 2,5:1") from None


def is_gost_scale(label: str) -> bool:
    return str(label).replace(" ", "").replace(".", ",") in GOST_SCALES


GENERATED = ("spec", "tt", "textdoc")    # таблицы и текст документа — не изображение детали, масштаб их не трогает


def set_sheet_scale(project, label: str) -> float:
    """Масштаб листа из ряда ГОСТ 2.302: изображение масштабируется вокруг своего центра, размерные числа
    по-прежнему показывают натуральную величину (множитель k размера), высота надписей не меняется.
    Возвращает, во сколько раз изменилось изображение."""
    label = str(label).replace(" ", "").replace(".", ",")
    if label not in GOST_SCALES:
        raise ValueError(f"масштаб {label} не из ряда ГОСТ 2.302: {', '.join(GOST_SCALES)}")
    if not project.frame:
        project.frame = default_frame()
    try:
        old = scale_factor(project.frame.get("scale", "1:1"))
    except ValueError:
        old = 1.0
    new = scale_factor(label)
    f = new / old
    ents = [e for e in project.drawing if e.get("gen") not in GENERATED]
    if ents and abs(f - 1) > 1e-12:
        from . import edit2d

        x0, y0, x1, y1 = library.bounds(ents)
        c = ((x0 + x1) / 2, (y0 + y1) / 2)
        for e in ents:
            edit2d._map_points(e, lambda p: (c[0] + (p[0] - c[0]) * f, c[1] + (p[1] - c[1]) * f))
            if e["type"] in ("circle", "arc", "diadim", "raddim"):
                e["r"] *= f
            if e["type"] in ("dim", "diadim", "raddim"):
                e["k"] = e.get("k", 1.0) / f              # число на размере — прежнее, натуральное
            if e.get("blk_at"):
                e["blk_at"][3] *= f
    project.frame["scale"] = label
    project.frame["scale_fixed"] = True                   # «Чертёж по модели» больше не подбирает масштаб сам
    return f


# ---------------------------------------------------------------- листы-продолжения и общие помощники
def _gen(ents, tag):
    for e in ents:
        e["gen"] = tag
    return ents


def _drop(project, tag):
    project.drawing[:] = [e for e in project.drawing if e.get("gen") != tag]


def _wrap(text: str, width: float, h: float) -> list[str]:
    """Перенос по словам в ширину width мм шрифтом высоты h."""
    per = max(4, int(width / (library.CHAR_W * h)))
    out = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split():
            while len(word) > per:                       # слово длиннее строки — режем
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:per])
                word = word[per:]
            if line and len(line) + 1 + len(word) > per:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return out


class _Pages:
    """Листы А4 документа (спецификация, записка). Если на листе проекта уже есть чертёж, документ ложится отдельными
    листами справа от него — чертёж не трогается; иначе первым листом становится сам лист проекта (форма 2).
    Следующие листы — форма 2а, рамка и основная надпись — линиями и надписями с пометкой gen."""

    def __init__(self, project, tag: str):
        self.project, self.tag = project, tag
        own = [e for e in project.drawing if e.get("gen") not in GENERATED]
        self.beside = bool(project.sheet() and own)
        if not self.beside:
            fr = project.frame or default_frame()
            fr.update(format="A4", orient="portrait", form="2")
            project.frame, project.canvas = fr, "sheet"
        self.pages: list[dict] = []

    def add(self) -> dict:
        base = self.project.frame
        i = len(self.pages)
        if self.beside:
            w, h = sheet_size(base["format"], base["orient"])
            row = 0.0 if self.tag == "spec" else -(297.0 + 20.0)       # записка — рядом ниже, чтобы не лечь на спецификацию
            page = {**base, "format": "A4", "orient": "portrait", "form": "2" if i == 0 else "2a",
                    "x": base.get("x", 0.0) + w + 20.0 + i * 230.0, "y": base.get("y", 0.0) + h - 297.0 + row}
        elif i == 0:
            page = base
        else:
            page = {**base, "x": base.get("x", 0.0) + i * 230.0, "form": "2a"}
        self.pages.append(page)
        return page

    def frames(self) -> list[dict]:
        """Рамки и основные надписи всех листов, кроме листа проекта; заодно проставляет «Лист» и «Листов»."""
        out, rects = [], []
        for i, page in enumerate(self.pages):
            page["sheet"], page["sheets"] = str(i + 1), str(len(self.pages))
            if page is self.project.frame:
                continue
            rects.append([page["x"], page["y"], *sheet_size(page["format"], page["orient"])])
            lines, texts = frame_geometry(page, self.project)
            out += [make_line(x1, y1, x2, y2, "main" if kind == "main" else "thin") for x1, y1, x2, y2, kind in lines]
            out += [make_text(x, y, t, h, 0.0, align) for x, y, h, t, align in texts]
        self.project.eskd.setdefault("pages", {})[self.tag] = rects     # где подложить «бумагу» под эти листы
        return out


# ---------------------------------------------------------------- ГОСТ 2.316: технические требования
def tech_entities(project, items: list[str], h: float = 3.5) -> list[dict]:
    """Нумерованные пункты над основной надписью колонкой шириной 185 мм; заголовок не пишется (ГОСТ 2.316)."""
    fr = project.frame
    fx, fy, fw, _ = frame_rect(fr)
    sw, sh = stamp_size(fr)
    x = fx + fw - sw + 2.0
    rows = []
    numbered = len(items) > 1
    for i, item in enumerate(items, 1):
        lines = _wrap(item, sw - 10.0, h)
        for j, s in enumerate(lines):
            rows.append(((f"{i} " if numbered else "") + s) if j == 0 else ("   " if numbered else "") + s)
    step = h * 1.8
    y = fy + sh + 5.0 + (len(rows) - 1) * step
    return _gen([make_text(x, y - k * step, s, h) for k, s in enumerate(rows)], "tt")


def set_tech_requirements(project, items) -> int:
    """Технические требования: пустые пункты выбрасываются, блок на листе заменяется. Возвращает число пунктов."""
    items = [str(s).strip() for s in items if str(s).strip()]
    if not project.sheet():
        raise ValueError("технические требования ставятся на лист с рамкой: выберите формат А4 или А3")
    project.eskd["tech"] = items
    _drop(project, "tt")
    project.drawing.extend(tech_entities(project, items))
    return len(items)


# ---------------------------------------------------------------- ГОСТ 2.105: текстовый документ
def set_text_document(project, text: str, h: float = 3.5) -> int:
    """Пояснительная записка: лист А4, форма 2 на первом листе и 2а на следующих. Строки «# Заголовок» — заголовки
    разделов, абзац — с отступом 15 мм. Возвращает число листов."""
    project.eskd["text"] = str(text)
    _drop(project, "textdoc")
    pages = _Pages(project, "textdoc")
    step = h * 2.0
    rows = []                                             # (отступ, высота, текст)
    for para in str(text).split("\n"):
        para = para.rstrip()
        if not para:
            rows.append((0.0, h, ""))
        elif para.startswith("#"):
            rows.append((15.0, 5.0, para.lstrip("# ").strip()))
        else:
            for j, s in enumerate(_wrap(para, 185.0 - 28.0, h)):
                rows.append((15.0 if j == 0 else 0.0, h, s))
    out, y, bottom, fx = [], 0.0, 1.0, 0.0
    for indent, hh, s in rows:
        if y < bottom:
            page = pages.add()
            fx, fy, fw, fh = frame_rect(page)
            y, bottom = fy + fh - 10.0 - h, fy + stamp_size(page)[1] + 10.0
        if s:
            out.append(make_text(fx + 5.0 + indent, y, s, hh))
        y -= step * (1.3 if hh > h else 1.0)
    if not pages.pages:
        pages.add()
    project.drawing.extend(_gen(out + pages.frames(), "textdoc"))
    return len(pages.pages)


# ---------------------------------------------------------------- ГОСТ 2.106: спецификация
SPEC_SECTIONS = ["Документация", "Сборочные единицы", "Детали", "Стандартные изделия", "Прочие изделия", "Материалы"]
SPEC_COLUMNS = [("format", "Формат", 6.0), ("zone", "Зона", 6.0), ("pos", "Поз.", 8.0), ("designation", "Обозначение", 70.0),
                ("name", "Наименование", 63.0), ("qty", "Кол.", 10.0), ("note", "Приме-\nчание", 22.0)]
_STANDARD = {"bolt": "Болт", "nut": "Гайка", "washer": "Шайба", "bearing": "Подшипник"}
_MATERIAL = ("tube_sq", "channel", "angle", "ibeam")
_NOT_ITEMS = ("weld", "axis_mark", "level", "wall", "partition", "door", "window", "gate", "stair", "column", "vent",
              "ground_loop", "pe")


def spec_row(section, name, designation="", qty="1", note="", fmt="", zone="", pos="") -> dict:
    return {"section": section, "format": fmt, "zone": zone, "pos": pos, "designation": designation, "name": name,
            "qty": str(qty), "note": note}


def collect_spec(project) -> list[dict]:
    """Строки спецификации из того, что есть в проекте: сборочный чертёж — в «Документацию», тело из дерева
    построения — в «Детали», крепёж и подшипники с листа — в «Стандартные изделия», прочие элементы библиотеки —
    в «Прочие изделия», прокат и материал детали — в «Материалы». Позиции нумеруются по порядку."""
    rows = []
    base = project.designation or "АБВГ.000000.001"
    fmt = (project.frame or {}).get("format", "A3").replace("A", "А")
    rows.append(spec_row("Документация", "Сборочный чертёж", f"{base} СБ", "", "", fmt))
    if project.features:
        rows.append(spec_row("Детали", project.name or "Деталь", _child(base, 1), 1, "", fmt))
    seen: dict[tuple, dict] = {}
    for ents in (project.drawing, project.entities):
        insts = {}
        for e in ents:
            if e.get("blk") and e.get("blk_id"):
                insts[e["blk"]] = e["blk_id"]
        for inst, bid in insts.items():
            stem = bid.rsplit("_", 1)[0] if bid.endswith(("_front", "_top")) else bid
            if bid in _NOT_ITEMS:
                continue
            blk = library.BLOCKS.get(bid)
            if blk is None:
                continue
            name = blk.name.split(" (")[0]
            label = library.label_of(ents, inst)
            section = ("Стандартные изделия" if stem in _STANDARD else "Материалы" if bid in _MATERIAL else "Прочие изделия")
            key = (section, name)
            row = seen.get(key)
            if row is None:
                row = seen[key] = spec_row(section, name, "", 0)
                row["_labels"] = []
            row["qty"] = str(int(row["qty"]) + 1)
            if label and section == "Прочие изделия":
                row["_labels"].append(label)
    for row in seen.values():
        labels = row.pop("_labels")
        row["note"] = ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "")
        if row["section"] == "Материалы":
            row["note"], row["qty"] = f"{row['qty']} шт.", ""
        rows.append(row)
    if project.material:
        rows.append(spec_row("Материалы", project.material, "", "", ""))
    return number_spec(rows)


def _child(base: str, n: int) -> str:
    """Обозначение составной части: последняя группа цифр обозначения изделия + n."""
    head, _, tail = base.rpartition(".")
    return f"{head}.{int(tail) + n:0{len(tail)}d}" if head and tail.isdigit() else f"{base}-{n:02d}"


def number_spec(rows: list[dict]) -> list[dict]:
    """Разделы — в порядке ГОСТ 2.106, внутри раздела — по наименованию; позиции 1, 2, 3… (у документации их нет)."""
    order = {s: i for i, s in enumerate(SPEC_SECTIONS)}
    rows = sorted(rows, key=lambda r: (order.get(r["section"], 99), r["section"] != "Документация" and r["name"].lower() or ""))
    pos = 0
    for r in rows:
        if r["section"] in ("Документация", "Материалы"):
            r["pos"] = ""
        else:
            pos += 1
            r["pos"] = str(pos)
    return rows


def spec_table_rows(rows: list[dict]) -> list[list[str]]:
    """Строки таблицы: заголовок раздела отдельной строкой (подчёркнут в «Наименовании»), пустая строка до и после."""
    out, section = [], None
    for r in rows:
        if r["section"] != section:
            section = r["section"]
            if out:
                out.append([""] * 7)
            out.append(["", "", "", "", f"§{section}", "", ""])
            out.append([""] * 7)
        out.append([r.get(k, "") for k, _, _ in SPEC_COLUMNS])
    return out


def build_specification(project, rows: list[dict] | None = None) -> dict:
    """Спецификация на листе А4 с основной надписью формы 2 (следующие листы — 2а). rows=None — собрать из проекта.
    Возвращает {"rows", "sheets"}."""
    rows = collect_spec(project) if rows is None else number_spec([dict(r) for r in rows])
    project.eskd["spec"] = rows
    _drop(project, "spec")
    pages = _Pages(project, "spec")
    widths = [w for _, _, w in SPEC_COLUMNS]
    heads = [t for _, t, _ in SPEC_COLUMNS]
    data = spec_table_rows(rows)
    out, start = [], 0
    while True:
        page = pages.add()
        fx, fy, fw, fh = frame_rect(page)
        cap = int((fh - stamp_size(page)[1] - 15.0) // 8.0)
        chunk = data[start:start + cap]
        ents = library.table(fx, fy + fh, widths, heads, rows=cap, row_h=8.0, head_h=15.0, data=_plain(chunk), vertical=(0, 1, 2))
        ents += _underline(chunk, fx + sum(widths[:4]), fy + fh - 15.0, widths[4])
        out += ents
        start += cap
        if start >= len(data):
            break
    project.drawing.extend(_gen(out + pages.frames(), "spec"))
    return {"rows": len(rows), "sheets": len(pages.pages), "beside": pages.beside}


def _plain(chunk):
    return [[c[1:] if c.startswith("§") else c for c in row] for row in chunk]


def _underline(chunk, x, ytop, w):
    """Заголовок раздела — по центру графы «Наименование» и подчёркнут тонкой линией."""
    out = []
    for r, row in enumerate(chunk):
        if row[4].startswith("§"):
            tw = min(w - 4.0, library.CHAR_W * 3.5 * (len(row[4]) - 1))
            y = ytop - (r + 1) * 8.0 + 1.4
            out.append(make_line(x + 1.5, y, x + 1.5 + tw, y, "thin"))
    return out


# ---------------------------------------------------------------- ГОСТ 2.701: шифр схемы
SCHEME_KINDS = {"Э": "электрическая", "Г": "гидравлическая", "П": "пневматическая", "Х": "газовая", "К": "кинематическая",
                "В": "вакуумная", "Л": "оптическая", "Р": "энергетическая", "Е": "деления", "С": "комбинированная"}
SCHEME_TYPES = {"1": "структурная", "2": "функциональная", "3": "принципиальная", "4": "соединений", "5": "подключения",
                "6": "общая", "7": "расположения", "0": "объединённая"}


def scheme_code(kind: str, type_: str) -> str:
    if kind not in SCHEME_KINDS or str(type_) not in SCHEME_TYPES:
        raise ValueError("вид схемы — " + ", ".join(SCHEME_KINDS) + "; тип — " + ", ".join(SCHEME_TYPES))
    return f"{kind}{type_}"


def scheme_title(code: str) -> str:
    return f"Схема {SCHEME_KINDS[code[0]]} {SCHEME_TYPES[code[1:]]}"


def set_scheme(project, kind: str, type_: str) -> str:
    """Шифр схемы в обозначение документа (графа 2 основной надписи): прежний шифр заменяется, наименование
    дополняется строкой вида «Схема электрическая принципиальная»."""
    code = scheme_code(kind, str(type_))
    old = project.eskd.get("scheme", "")
    base = project.designation.strip()
    if old and base.endswith(old):
        base = base[:-len(old)].rstrip()
    project.designation = f"{base} {code}".strip()
    title = scheme_title(code)
    name = project.name
    if old and scheme_title(old) in name:
        name = name.replace(scheme_title(old), title)
    elif title not in name:
        name = f"{name}. {title}" if name and name != "Деталь" else title
    project.name = name
    project.eskd["scheme"] = code
    return code


# ---------------------------------------------------------------- нормоконтроль
def normcontrol(project) -> list[dict]:
    """Проверка листа по ЕСКД. Каждая запись: level (ok | warn | error), gost, text и ids объектов."""
    out = []

    def add(level, gost, text, ids=()):
        out.append({"level": level, "gost": gost, "text": text, "ids": list(ids)})

    fr = project.sheet()
    if fr is None:
        add("error", "ГОСТ 2.301-68", "Чертёж на бесконечном полотне: выберите формат листа с рамкой (А4, А3…)")
    else:
        w, h = sheet_size(fr["format"], fr["orient"])
        add("ok", "ГОСТ 2.301-68", f"Формат {fr['format'].replace('A', 'А').replace('x', '×')} ({w:g} × {h:g} мм)")
        form = form_of(fr)
        add("ok", "ГОСТ 2.104-2006", f"Основная надпись: {FORMS[form][0].lower()}")
        need = [("designation", "обозначение (графа 2)"), ("name", "наименование (графа 1)")]
        if form == "1" and project.eskd.get("doc", "part") in ("part", "sheet_metal") and not project.eskd.get("scheme"):
            need.append(("material", "материал (графа 3)"))
        empty = [label for key, label in need if not str(getattr(project, key, "") or "").strip()]
        people = fr.get("people") or {}
        empty += [f"«{role}»" for role in ("Разраб.", "Пров.") if form != "2a" and not str(people.get(role, "")).strip()]
        if empty:
            add("error", "ГОСТ 2.104-2006", "Не заполнены графы основной надписи: " + ", ".join(empty))
        else:
            add("ok", "ГОСТ 2.104-2006", "Обязательные графы основной надписи заполнены")
        soft = [f"«{role}»" for role in ("Н. контр.", "Утв.") if form != "2a" and not str(people.get(role, "")).strip()]
        if soft:
            add("warn", "ГОСТ 2.104-2006", "Нет подписей: " + ", ".join(soft))
        if form == "1":
            sc = str(fr.get("scale", "")).strip()
            if is_gost_scale(sc):
                add("ok", "ГОСТ 2.302-68", f"Масштаб {sc} — из стандартного ряда")
            else:
                add("error", "ГОСТ 2.302-68", f"Масштаб «{sc or 'не указан'}» не из ряда: {', '.join(GOST_SCALES)}")
        # линии и надписи — внутри рамки и не на основной надписи
        fx, fy, fw, fh = frame_rect(fr)
        sw, sh = stamp_size(fr)
        outside, on_stamp = [], []
        for e in project.drawing:
            if e.get("gen") in GENERATED:
                continue
            try:
                x0, y0, x1, y1 = library.bounds([e])
            except (ValueError, KeyError):
                continue
            if x0 < fx - 1e-6 or y0 < fy - 1e-6 or x1 > fx + fw + 1e-6 or y1 > fy + fh + 1e-6:
                outside.append(e["id"])
            elif x1 > fx + fw - sw + 1e-6 and y0 < fy + sh - 1e-6:
                on_stamp.append(e["id"])
        if outside:
            add("error", "ГОСТ 2.109-73", f"За рамкой листа объектов: {len(outside)}", outside)
        if on_stamp:
            add("error", "ГОСТ 2.104-2006", f"На основную надпись заходит объектов: {len(on_stamp)}", on_stamp)
        if not outside and not on_stamp:
            add("ok", "ГОСТ 2.109-73", "Изображение в пределах рамки и не заходит на основную надпись")
    s = float(project.eskd.get("s", 0.5))
    if S_MIN - 1e-9 <= s <= S_MAX + 1e-9:
        add("ok", "ГОСТ 2.303-68", f"Толщина основной линии s = {s:g} мм (допустимо {S_MIN:g}…{S_MAX:g}); тонкие — от s/3 до s/2")
    else:
        add("error", "ГОСТ 2.303-68", f"Толщина основной линии s = {s:g} мм вне диапазона {S_MIN:g}…{S_MAX:g} мм")
    bad = [e["id"] for e in project.drawing if e.get("style") not in STYLES]
    if bad:
        add("error", "ГОСТ 2.303-68", f"Линий с типом не из стандарта: {len(bad)}", bad)
    used = sorted({e["style"] for e in project.drawing if e["type"] in ("line", "circle", "arc") and e.get("style") in STYLES},
                  key=STYLES.index)
    if used:
        add("ok", "ГОСТ 2.303-68", "Типы линий на листе: " + ", ".join(STYLE_LABEL[k].split(" (")[0].lower() for k in used))
    odd = [e["id"] for e in project.drawing if e["type"] == "text" and e.get("gen") not in GENERATED and not e.get("blk")
           and min(abs(e["h"] - v) for v in FONT_SIZES) > 0.05]
    if odd:
        add("warn", "ГОСТ 2.304-81", f"Надписей с высотой шрифта не из ряда {', '.join(f'{v:g}' for v in FONT_SIZES)}: {len(odd)}", odd)
    else:
        add("ok", "ГОСТ 2.304-81", "Высоты шрифта надписей — из стандартного ряда")
    curves = [e for e in project.drawing if e["type"] in ("line", "circle", "arc") and e.get("style") == "main"]
    dims = [e for e in project.drawing if e["type"] in ("dim", "diadim", "raddim", "angdim")]
    if curves and not dims and project.eskd.get("doc") not in ("text", "spec"):
        add("warn", "ГОСТ 2.307-2011", "На чертеже нет ни одного размера")
    elif dims:
        add("ok", "ГОСТ 2.307-2011", f"Размеров на листе: {len(dims)}")
    return out


def norm_summary(findings: list[dict]) -> str:
    e = sum(1 for f in findings if f["level"] == "error")
    w = sum(1 for f in findings if f["level"] == "warn")
    return "замечаний нет" if not e and not w else f"ошибок {e}, предупреждений {w}"


# ---------------------------------------------------------------- справочник
def _g(num, title, group, text, table=None, actions=()):
    return {"num": num, "title": title, "group": group, "text": text, "table": table, "actions": list(actions)}


G0, G1, G2, G3, G7 = ("0. Общие положения", "1. Основные положения", "2. Обозначение изделий и документов",
                      "3. Общие правила выполнения чертежей", "7. Правила выполнения схем")

GOSTS = [
    _g("2.001-2013", "Общие положения", G0,
       "ЕСКД — комплекс стандартов с едиными правилами разработки, оформления и обращения конструкторской документации. "
       "Номер стандарта: 2 — класс ЕСКД, первая цифра после точки — группа (0 — общие положения, 1 — основные положения, "
       "3 — правила выполнения чертежей, 7 — схемы), далее порядковый номер и год."),
    _g("2.101-2016", "Виды изделий", G1,
       "Изделия делятся на детали (без сборочных операций), сборочные единицы, комплексы и комплекты. От вида изделия "
       "зависит набор документов: у детали основной документ — чертёж детали, у сборочной единицы — спецификация."),
    _g("2.102-2013", "Виды и комплектность конструкторских документов", G1,
       "Какие документы бывают и какой шифр добавляется к обозначению. Чертёж детали и спецификация шифра не имеют.",
       [["Документ", "Шифр"], ["Чертёж детали", "—"], ["Сборочный чертёж", "СБ"], ["Чертёж общего вида", "ВО"],
        ["Габаритный чертёж", "ГЧ"], ["Электромонтажный чертёж", "МЭ"], ["Монтажный чертёж", "МЧ"], ["Схема", "по ГОСТ 2.701"],
        ["Спецификация", "—"], ["Ведомость покупных изделий", "ВП"], ["Пояснительная записка", "ПЗ"],
        ["Технические условия", "ТУ"], ["Расчёт", "РР"]],
       [("Спецификация…", "spec"), ("Текстовый документ (ПЗ)…", "textdoc"), ("Шифр схемы…", "scheme")]),
    _g("2.103-2013", "Стадии разработки", G1,
       "Стадии: техническое предложение (литера П), эскизный проект (Э), технический проект (Т), рабочая конструкторская "
       "документация (О, О1, А). Литера записывается в графу «Лит.» основной надписи."),
    _g("2.104-2006", "Основные надписи", G1,
       "Основная надпись стоит в правом нижнем углу листа. Форма 1 — первый лист чертежей и схем; форма 2 — первый лист "
       "текстовых документов и спецификаций; форма 2а — последующие листы. Двойной щелчок по графе на листе открывает её правку.",
       [["Форма", "Размер, мм", "Где применяется"], ["1", "185 × 55", "чертежи и схемы, первый лист"],
        ["2", "185 × 40", "текстовые документы, спецификации, первый лист"], ["2а", "185 × 15", "последующие листы"]],
       [("Форма 1 (185×55)", "stamp:1"), ("Форма 2 (185×40)", "stamp:2"), ("Форма 2а (185×15)", "stamp:2a"), ("Заполнить графы…", "stamp_edit")]),
    _g("2.105-95", "Общие требования к текстовым документам", G1,
       "Текст — на листах А4 с рамкой и основной надписью (форма 2, далее 2а). От рамки до текста в начале и конце строк — "
       "не меньше 3 мм, сверху и снизу — не меньше 10 мм, абзацный отступ 15–17 мм. Разделы нумеруются арабскими цифрами.",
       None, [("Текстовый документ…", "textdoc")]),
    _g("2.106-96", "Текстовые документы. Спецификация", G1,
       "Спецификация определяет состав сборочной единицы. Разделы идут в установленном порядке; название раздела пишется "
       "в графе «Наименование» и подчёркивается. Программа собирает строки из дерева построения и элементов библиотеки на листе.",
       [["Раздел", "Что в него попадает"], ["Документация", "сборочный чертёж, схемы, записка"], ["Сборочные единицы", "узлы со своей спецификацией"],
        ["Детали", "детали по чертежам"], ["Стандартные изделия", "болты, гайки, шайбы, подшипники по ГОСТ"],
        ["Прочие изделия", "покупные изделия по ТУ и каталогам"], ["Материалы", "прокат, провод, краска"]],
       [("Собрать спецификацию…", "spec")]),
    _g("2.109-73", "Основные требования к чертежам", G1,
       "Чертёж детали содержит всё, что нужно для изготовления и контроля: изображения, размеры с отклонениями, шероховатость, "
       "материал, технические требования. Каждый размер наносится один раз. Изображение не выходит за рамку.",
       None, [("Нормоконтроль", "norm")]),
    _g("2.201-80", "Обозначение изделий и конструкторских документов", G2,
       "Обозначение: код организации-разработчика (4 знака), код классификационной характеристики (6 цифр), порядковый номер "
       "(3 цифры) — например АБВГ.301412.001. К обозначению документа добавляется шифр: СБ, Э3, ПЗ."),
    _g("2.301-68", "Форматы", G3,
       "Основные форматы получаются делением А0 пополам; кратные — увеличением короткой стороны основного формата в целое число раз.",
       [["Формат", "Размер, мм"]] + [[k.replace("A", "А").replace("x", "×"), f"{v[0]:g} × {v[1]:g}"] for k, v in FORMATS.items()],
       [("Формат листа…", "format")]),
    _g("2.302-68", "Масштабы", G3,
       "Масштаб выбирается из ряда. При смене масштаба листа изображение пересчитывается, а размерные числа по-прежнему "
       "показывают действительный размер детали.",
       [["Уменьшения", "Натуральная", "Увеличения"], ["1:2; 1:2,5; 1:4; 1:5; 1:10; 1:20; 1:50; 1:100", "1:1", "2:1; 2,5:1; 4:1; 5:1; 10:1"]],
       [("Масштаб листа…", "scale")]),
    _g("2.303-68", "Линии", G3,
       f"Толщина основной линии s — от {S_MIN:g} до {S_MAX:g} мм, одна на всех изображениях чертежа. Остальные толщины считаются от s.",
       [["Линия", "Толщина", "Для чего"],
        ["Сплошная толстая основная", "s", "видимый контур"], ["Сплошная тонкая", "s/3…s/2", "размерные, выносные, штриховка"],
        ["Сплошная волнистая", "s/3…s/2", "линия обрыва"], ["Штриховая", "s/3…s/2", "невидимый контур"],
        ["Штрихпунктирная тонкая", "s/3…s/2", "осевые и центровые"], ["Штрихпунктирная утолщённая", "s/2…2s/3", "поверхности под обработку, покрытие"],
        ["Разомкнутая", "s…1,5s", "линия сечения"], ["Сплошная тонкая с изломами", "s/3…s/2", "длинная линия обрыва"],
        ["Штрихпунктирная с двумя точками", "s/3…s/2", "линии сгиба, крайние положения"]],
       [("Толщина s…", "thickness")] + [(STYLE_LABEL[k].split(" (")[0], f"style:{k}") for k in ("axis_thick", "open", "zigzag")]),
    _g("2.304-81", "Шрифты чертёжные", G3,
       "Размер шрифта h — высота прописных букв в мм. Тип А — толщина линии h/14, тип Б — h/10; оба бывают с наклоном около 75° "
       "и без наклона.",
       [["Размеры шрифта h, мм"], ["1,8 (не рекомендуется); 2,5; 3,5; 5; 7; 10; 14; 20; 28; 40"]],
       [("Шрифт чертежа…", "font")]),
    _g("2.305-2008", "Изображения — виды, разрезы, сечения", G3,
       "Изображения строятся прямоугольным проецированием. Главный вид — спереди; вид сверху — под ним, вид слева — справа от него. "
       "Разрез показывает то, что в секущей плоскости и за ней, сечение — только то, что в плоскости.",
       None, [("Чертёж по модели", "views"), ("Изометрия на лист", "iso")]),
    _g("2.306-68", "Обозначения графические материалов в сечениях", G3,
       "Штриховка металла — параллельные линии под 45° с шагом 1–10 мм, одинаковая на всех сечениях одной детали.",
       [["Материал", "Рисунок"], ["Металлы", "наклонные линии 45°"], ["Неметаллы", "сетка"], ["Дерево", "линии годичных слоёв"],
        ["Стекло", "группы коротких штрихов"], ["Бетон", "штрихи и точки"], ["Жидкость", "горизонтальные штриховые"],
        ["Грунт естественный", "группы наклонных штрихов"]],
       [(v, f"hatch:{k}") for k, v in HATCH_PATTERNS.items()]),
    _g("2.307-2011", "Нанесение размеров и предельных отклонений", G3,
       "Размеры — в миллиметрах без обозначения единицы. Размерная линия — не ближе 10 мм от контура и 7 мм от соседней размерной; "
       "выносные выходят за стрелки на 1–5 мм. Отклонения пишут после размера: 40±0,1; 20H7; 20H7/g6.",
       None, [("Линейный размер", "dims")]),
    _g("2.308-2011", "Указания допусков формы и расположения поверхностей", G3,
       "Допуск записывается в рамке из двух или трёх полей: знак допуска, значение, обозначение базы. Знаки: прямолинейность, "
       "плоскостность, круглость, цилиндричность, параллельность, перпендикулярность, соосность, симметричность, биение."),
    _g("2.309-73", "Обозначения шероховатости поверхностей", G3,
       "Шероховатость задаётся знаком с параметром Ra (предпочтительно) или Rz в микрометрах. Знак ставят на линию контура, "
       "выносную линию или полку выноски.", None, [("Шероховатость", "rough")]),
    _g("2.311-68", "Изображение резьбы", G3,
       "Наружная резьба: наружный диаметр — сплошная основная линия, внутренний — сплошная тонкая; на виде с торца тонкая линия — "
       "дуга примерно на 3/4 окружности. Обозначение метрической резьбы: М12, М12×1,5-6g.",
       None, [("Размер с обозначением М…", "thread")]),
    _g("2.312-72", "Условные изображения и обозначения швов сварных соединений", G3,
       "Видимый шов — сплошная основная линия, невидимый — штриховая. Обозначение пишут на полке линии-выноски с односторонней "
       "стрелкой: над полкой — для лицевой стороны, под полкой — для оборотной.", None, [("Обозначение шва", "weld")]),
    _g("2.316-2008", "Правила нанесения надписей, технических требований и таблиц", G3,
       "Технические требования размещают над основной надписью колонкой шириной не более 185 мм. Пункты нумеруют, каждый "
       "с новой строки; заголовок «Технические требования» не пишут.", None, [("Технические требования…", "tech")]),
    _g("2.317-2011", "Аксонометрические проекции", G3,
       "Прямоугольная изометрия: углы между осями 120°, коэффициент искажения по осям 0,82, обычно принимают 1 (изображение "
       "крупнее в 1,22 раза); окружность становится эллипсом с осями 1,22d и 0,71d. Прямоугольная диметрия: по осям x и z — 0,94 "
       "(принимают 1), по y — 0,47 (принимают 0,5); ось x наклонена к горизонтали на 7°10′, ось y — на 41°25′.",
       None, [("Изометрия ГОСТ в 3D", "iso3d"), ("Диметрия ГОСТ в 3D", "dim3d"), ("Изометрия на лист", "iso"), ("Изометрическая сетка", "isogrid")]),
    _g("2.701-2008", "Схемы. Виды и типы. Общие требования к выполнению", G7,
       "Шифр схемы — буква вида и цифра типа: Э3 — электрическая принципиальная, Г1 — гидравлическая структурная.",
       [["Вид", "Буква", "Тип", "Цифра"]] + [[v, k, t, n] for (k, v), (n, t) in zip(SCHEME_KINDS.items(), SCHEME_TYPES.items())],
       [("Шифр схемы в штамп…", "scheme")]),
    _g("2.702-2011", "Правила выполнения электрических схем", G7,
       "Элементы изображают условными графическими обозначениями в отключённом положении, линии связи — горизонтальные и "
       "вертикальные с наименьшим числом изломов и пересечений. Каждому элементу присваивают позиционное обозначение.",
       None, [("Библиотека УГО", "library:electro")]),
    _g("2.710-81", "Обозначения буквенно-цифровые в электрических схемах", G7,
       "Буквенные коды: QF — автоматический выключатель, QS — разъединитель, FU — предохранитель, KM — контактор, "
       "M — двигатель, T — трансформатор, PI — счётчик, XS — розетка. После букв — порядковый номер: QF1, QF2."),
    _g("2.721-74", "Обозначения условные графические в схемах. Обозначения общего применения", G7,
       "Общие элементы УГО: линии связи, заземление, корпус, направление потока, регулирование. Размеры УГО можно "
       "пропорционально менять, сохраняя соотношения.", None, [("Библиотека УГО", "library:electro")]),
    _g("2.755-87", "УГО. Устройства коммутационные и контактные соединения", G7,
       "Контакты выключателей, разъединителей, реле; квалифицирующие знаки функций: выключателя, разъединителя, "
       "автоматического срабатывания.", None, [("Библиотека УГО", "library:electro")]),
]


def search(query: str = "") -> list[dict]:
    """Стандарты по номеру («2.104», «104») или словам названия и текста; пустой запрос — все."""
    q = " ".join(str(query).lower().replace("гост", "").split())
    if not q:
        return list(GOSTS)
    # основа слова: «шероховатость» находит «шероховатости», «масштаб» — «масштабы»
    words = [w if len(w) <= 5 or w[0].isdigit() else w[:-2] for w in q.split()]

    def rank(g):
        hay_num, hay = g["num"].lower(), f"{g['title']} {g['text']} " + " ".join(" ".join(r) for r in (g["table"] or []))
        hay = hay.lower()
        score = 0
        for w in words:
            if w in hay_num:
                score += 5
            elif w in g["title"].lower():
                score += 3
            elif w in hay:
                score += 1
            else:
                return 0
        return score
    scored = [(rank(g), i, g) for i, g in enumerate(GOSTS)]
    return [g for s, _, g in sorted((x for x in scored if x[0]), key=lambda x: (-x[0], x[1]))]


def by_num(num: str) -> dict | None:
    return next((g for g in GOSTS if g["num"].startswith(num)), None)


def html_page(g: dict) -> str:
    """Статья справочника для QTextBrowser."""
    import html

    out = [f"<h3>ГОСТ {html.escape(g['num'])}</h3><p><b>{html.escape(g['title'])}</b><br><small>{html.escape(g['group'])}</small></p>",
           f"<p>{html.escape(g['text'])}</p>"]
    if g["table"]:
        out.append('<table border="1" cellspacing="0" cellpadding="3">')
        for i, row in enumerate(g["table"]):
            tag = "th" if i == 0 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{html.escape(str(c))}</{tag}>" for c in row) + "</tr>")
        out.append("</table>")
    return "".join(out)

