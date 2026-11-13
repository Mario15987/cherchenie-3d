"""Вложения чата ИИ: фото чертежей и деталей, документы Word (.docx), текст (.txt, .csv, .json).

Работает без сети и внешних программ, в том числе в собранном .exe: .docx — zip-архив с XML, его разбирают zipfile и
xml.etree (python-docx не нужен); фото поворачивает по EXIF и сжимает Pillow, сводку геометрии считает cad.vision.
Без Qt — проверяется в тестах ядра.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
DOC_EXT = (".docx",)
TEXT_EXT = (".txt", ".csv", ".json")
ALL_EXT = IMAGE_EXT + DOC_EXT + TEXT_EXT
FILTERS = {
    "all": "Фото и документы (*.png *.jpg *.jpeg *.webp *.bmp *.docx *.txt *.csv *.json)",
    "image": "Фото и сканы (*.png *.jpg *.jpeg *.webp *.bmp)",
    "doc": "Word и текст (*.docx *.txt *.csv *.json)",
}
MAX_SIDE = 1600            # длинная сторона фото после сжатия, px
JPEG_QUALITY = 88
MAX_DOC_IMAGES = 8         # рисунков из одного документа
MIN_IMAGE = 48             # меньше по обеим сторонам — значки и логотипы, не чертежи
MAX_TEXT = 40_000          # символов документа в запрос
MAX_FILE = 60 * 2 ** 20    # файл и часть архива .docx — не больше 60 МБ
MAX_TABLE_ROWS = 400

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
# Символы шрифта Symbol, которыми в ТЗ пишут диаметр, градусы и допуски (w:sym w:char="F0C6").
SYMBOL_CHARS = {0xC6: "Ø", 0xB0: "°", 0xB1: "±", 0xD7: "×", 0xA3: "≤", 0xB3: "≥", 0xB9: "≠", 0xBB: "≈", 0xD6: "√",
                0x61: "α", 0x62: "β", 0x67: "γ", 0x44: "Δ", 0x64: "δ", 0x6D: "μ", 0x70: "π", 0x46: "Φ", 0x6A: "φ"}


class AttachError(Exception):
    pass


@dataclass
class Attachment:
    kind: str                         # image | docx | text
    name: str
    data: bytes = b""                 # image: JPEG после сжатия
    media_type: str = ""
    text: str = ""                    # docx, text — содержимое (таблицы в Markdown); image — сводка локального анализа
    tables: list = field(default_factory=list)
    size: tuple = (0, 0)              # image: после сжатия
    source_size: tuple = (0, 0)       # image: как было
    parent: str = ""                  # image: из какого документа извлечена
    info: dict = field(default_factory=dict)
    thumb: bytes = b""                # image: PNG 96 px для ленты вложений и переписки

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.b64}"

    @property
    def badge(self) -> str:
        return "IMG" if self.kind == "image" else Path(self.name).suffix[1:].upper() or "TXT"

    def caption(self) -> str:
        """Короткая подпись под именем в ленте вложений."""
        if self.kind == "image":
            return f"{self.size[0]}×{self.size[1]}" + (f" · из «{self.parent}»" if self.parent else "")
        if self.kind == "docx":
            i = self.info
            return f"Word · абз. {i.get('paragraphs', 0)} · табл. {i.get('tables', 0)} · рис. {i.get('images', 0)}"
        return f"{self.badge} · {len(self.text)} симв."

    def prompt_text(self) -> str:
        """Как документ попадает в запрос ИИ."""
        if self.kind == "docx":
            i = self.info
            pics = f", {i['attached']} рисунков приложены ниже как изображения" if i.get("attached") else ""
            return (f"Документ Word «{self.name}»: абзацев {i.get('paragraphs', 0)}, таблиц {i.get('tables', 0)}{pics}. "
                    f"Таблицы — в Markdown, рисунки отмечены [рисунок N].\n--- начало документа ---\n{self.text}\n--- конец документа ---")
        return f"Файл «{self.name}»:\n--- начало ---\n{self.text}\n--- конец ---"


def load(path) -> list[Attachment]:
    """Файл → вложения. Из .docx — сам документ и его рисунки отдельными картинками."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".doc":
        raise AttachError(f"«{p.name}»: старый формат Word (.doc) — сохраните документ как .docx")
    if ext not in ALL_EXT:
        raise AttachError(f"«{p.name}»: такие файлы не прикрепляются. Можно: {' '.join(ALL_EXT)}")
    try:
        if p.stat().st_size > MAX_FILE:
            raise AttachError(f"«{p.name}»: файл больше {MAX_FILE // 2 ** 20} МБ")
        raw = p.read_bytes()
    except OSError as exc:
        raise AttachError(f"«{p.name}»: не удалось прочитать ({exc.strerror or exc})") from exc
    if ext in IMAGE_EXT:
        return [image(raw, p.name)]
    if ext in DOC_EXT:
        return docx_attachments(raw, p.name)
    return [text_file(raw, p.name)]


# ---------------------------------------------------------------- изображения
def image(raw: bytes, name: str, parent: str = "", analyze: bool = True, min_side: int = 0) -> Attachment | None:
    """Фото → JPEG не больше MAX_SIDE по длинной стороне, повёрнутый по EXIF, прозрачность — на белом.
    min_side: картинка меньше этого по обеим сторонам — None (значки в документах)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        im = Image.open(io.BytesIO(raw))
        src = im.size
        if min_side and max(src) < min_side:
            return None
        if im.format == "JPEG" and max(src) > MAX_SIDE:  # 12-Мп снимок с телефона декодируется сразу уменьшенным
            k = MAX_SIDE / max(src)
            im.draft("RGB", (int(src[0] * k) + 1, int(src[1] * k) + 1))
        im.load()
        im = ImageOps.exif_transpose(im)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise AttachError(f"«{name}»: не удалось открыть как изображение ({exc})") from exc
    im = _flatten(im)
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True)   # 4:4:4 — тонкие линии не расплываются
    small = im.copy()
    small.thumbnail((96, 96), Image.LANCZOS)
    tb = io.BytesIO()
    small.save(tb, "PNG")
    att = Attachment("image", name, buf.getvalue(), "image/jpeg", size=im.size, source_size=src, parent=parent, thumb=tb.getvalue())
    if analyze:
        from . import vision

        att.info = vision.analyze(im)
        att.text = vision.summary(att.info)
    return att


def _flatten(im):
    from PIL import Image

    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    if im.mode.startswith("I;16") or im.mode == "I":
        im = im.point(lambda v: v / 256).convert("L")
    return im.convert("RGB")


# ---------------------------------------------------------------- текстовые файлы
def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def text_file(raw: bytes, name: str) -> Attachment:
    text = decode(raw)
    ext = Path(name).suffix.lower()
    tables = []
    if ext == ".csv":
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
        tables = [rows[:MAX_TABLE_ROWS]]
        text = markdown_table(tables[0]) + (f"\n(показаны {MAX_TABLE_ROWS} строк из {len(rows)})" if len(rows) > MAX_TABLE_ROWS else "")
    elif ext == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    return Attachment("text", name, text=_clip(text), tables=tables, info={"chars": len(text)})


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"\n…(обрезано: показано {MAX_TEXT} из {len(text)} символов)"


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)

    def line(r):
        cells = [c.replace("|", "\\|").replace("\n", " / ").strip() for c in r] + [""] * (width - len(r))
        return "| " + " | ".join(cells) + " |"
    return "\n".join([line(rows[0]), "|" + "---|" * width] + [line(r) for r in rows[1:]])


# ---------------------------------------------------------------- Word (.docx)
@dataclass
class DocxContent:
    markdown: str
    paragraphs: list            # текст абзацев и заголовков по порядку
    headings: list              # (уровень, текст)
    tables: list                # таблица — список строк, строка — список ячеек
    images: list                # (имя в архиве, байты): сначала по порядку в тексте, затем прочие из word/media


def docx_attachments(raw: bytes, name: str) -> list[Attachment]:
    doc = parse_docx(raw, name)
    pics, skipped = [], 0
    stem = Path(name).stem
    for k, (part, blob) in enumerate(doc.images, 1):
        if len(pics) >= MAX_DOC_IMAGES:
            skipped += 1
            continue
        try:
            att = image(blob, f"{stem} — рисунок {k}{Path(part).suffix.lower()}", parent=name, min_side=MIN_IMAGE)
        except AttachError:          # EMF/WMF без растра, повреждённый рисунок
            skipped += 1
            continue
        if att is not None:
            att.info["index"] = k
            pics.append(att)
    info = {"paragraphs": len(doc.paragraphs), "tables": len(doc.tables), "images": len(doc.images),
            "attached": len(pics), "skipped": skipped, "headings": len(doc.headings)}
    return [Attachment("docx", name, text=_clip(doc.markdown), tables=doc.tables, info=info), *pics]


def _limited(z: zipfile.ZipFile, part: str) -> bytes:
    info = z.getinfo(part)
    if info.file_size > MAX_FILE:
        raise AttachError(f"часть архива {part} больше {MAX_FILE // 2 ** 20} МБ")
    return z.read(part)


def _xml(z, part):
    try:
        return ET.fromstring(_limited(z, part))
    except ET.ParseError as exc:
        raise AttachError(f"повреждён XML {part}: {exc}") from exc


def _rels(z, part: str, base: str, names: set) -> dict:
    """rId → путь внутри архива (внешние ссылки пропускаются)."""
    if part not in names:
        return {}
    out = {}
    for rel in _xml(z, part).iter(f"{PKG}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
        out[rel.get("Id")] = (path, rel.get("Type", ""))
    return out


def _styles(z, part, names) -> dict:
    """styleId → (уровень заголовка, список ли): по outlineLvl и numPr стиля, имени «heading N» / «Заголовок N»,
    «List …» и цепочке basedOn. Уровень 0 — не заголовок."""
    if part not in names:
        return {}
    raw = {}
    for st in _xml(z, part).iter(f"{W}style"):
        sid = st.get(f"{W}styleId")
        nm = st.find(f"{W}name")
        lvl = st.find(f"{W}pPr/{W}outlineLvl")
        base = st.find(f"{W}basedOn")
        raw[sid] = (nm.get(f"{W}val", "") if nm is not None else "", lvl.get(f"{W}val") if lvl is not None else None,
                    base.get(f"{W}val") if base is not None else None, st.find(f"{W}pPr/{W}numPr") is not None)

    def level(sid, depth=0):
        if sid not in raw or depth > 6:
            return 0
        name, lvl, base, _ = raw[sid]
        if lvl is not None and lvl.isdigit() and int(lvl) < 9:
            return int(lvl) + 1
        m = re.match(r"(heading|заголовок)\s*(\d)", name, re.I)
        if m:
            return int(m.group(2))
        if name.lower() in ("title", "название", "заглавие"):
            return 1
        return level(base, depth + 1) if base else 0

    def listy(sid, depth=0):
        if sid not in raw or depth > 6:
            return False
        name, _, base, num = raw[sid]
        return num or name.lower().startswith(("list", "список")) or (bool(base) and listy(base, depth + 1))
    return {sid: (level(sid), listy(sid)) for sid in raw}


def parse_docx(raw: bytes, name: str = "документ") -> DocxContent:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise AttachError(f"«{name}»: файл повреждён или это не .docx (не zip-архив)") from exc
    with z:
        names = set(z.namelist())
        main = next((p for p, t in _rels(z, "_rels/.rels", "", names).values() if t.endswith("/officeDocument")), "word/document.xml")
        if main not in names:
            raise AttachError(f"«{name}»: в архиве нет {main} — это не документ Word")
        try:
            root = _xml(z, main)
            base = posixpath.dirname(main)
            rels = _rels(z, f"{base}/_rels/{posixpath.basename(main)}.rels", base, names)
            styles = _styles(z, f"{base}/styles.xml", names)
        except AttachError as exc:
            raise AttachError(f"«{name}»: {exc}") from exc
        walker = _Walker(rels, styles)
        body = root.find(f"{W}body")
        if body is not None:
            walker.block(body)
        media = [p for p in sorted(names) if p.startswith(f"{base}/media/")]
        order = walker.pictures + [p for p in media if p not in walker.pictures]
        images = []
        for part in order:
            if part in names and z.getinfo(part).file_size <= MAX_FILE:
                images.append((posixpath.basename(part), z.read(part)))
    return DocxContent("\n\n".join(walker.md), walker.paragraphs, walker.headings, walker.tables, images)


class _Walker:
    """Обход тела документа по порядку: абзацы, заголовки, списки, таблицы, надписи, рисунки."""

    def __init__(self, rels, styles):
        self.rels, self.styles = rels, styles
        self.md, self.paragraphs, self.headings, self.tables, self.pictures = [], [], [], [], []

    def block(self, container):
        for el in container:
            t = el.tag
            if t == f"{W}p":
                self.paragraph(el)
            elif t == f"{W}tbl":
                rows = self.table(el)
                if rows:
                    self.tables.append(rows)
                    self.md.append(markdown_table(rows))
            elif t == f"{W}sdt":
                c = el.find(f"{W}sdtContent")
                if c is not None:
                    self.block(c)
            elif t in (f"{W}customXml", f"{W}ins", f"{W}smartTag"):
                self.block(el)
            elif t == f"{MC}AlternateContent":
                self.block(_choice(el))

    def paragraph(self, p):
        out, boxes, pics = [], [], []
        _runs(p, out, boxes, pics)
        text = "".join(out).strip()
        marks = []
        for rid in pics:
            part = self.rels.get(rid, ("", ""))[0]
            if not part:
                continue
            if part not in self.pictures:
                self.pictures.append(part)
            marks.append(f"[рисунок {self.pictures.index(part) + 1}]")
        if text:
            self.paragraphs.append(text)
            lvl, listy = self._style(p)
            if lvl:
                self.headings.append((lvl, text))
                text = "#" * min(lvl, 6) + " " + text
            elif listy:
                text = "- " + text
        line = " ".join([text] * bool(text) + marks)
        if line:
            self.md.append(line)
        for box in boxes:                   # текст надписей — после абзаца, в котором они стоят
            self.block(box)

    def _style(self, p) -> tuple[int, bool]:
        """(уровень заголовка, пункт списка) — по свойствам абзаца, иначе по его стилю."""
        ppr = p.find(f"{W}pPr")
        if ppr is None:
            return 0, False
        st = ppr.find(f"{W}pStyle")
        lvl, listy = self.styles.get(st.get(f"{W}val"), (0, False)) if st is not None else (0, False)
        own = ppr.find(f"{W}outlineLvl")
        if own is not None and own.get(f"{W}val", "9").isdigit() and int(own.get(f"{W}val")) < 9:
            lvl = int(own.get(f"{W}val")) + 1
        return lvl, listy or ppr.find(f"{W}numPr") is not None

    def table(self, tbl) -> list[list[str]]:
        rows = []
        for tr in _direct(tbl, f"{W}tr"):
            row = []
            before = tr.find(f"{W}trPr/{W}gridBefore")
            if before is not None and before.get(f"{W}val", "0").isdigit():
                row += [""] * int(before.get(f"{W}val"))
            for tc in _direct(tr, f"{W}tc"):
                pr = tc.find(f"{W}tcPr")
                span = pr.find(f"{W}gridSpan") if pr is not None else None
                span = int(span.get(f"{W}val", "1")) if span is not None and span.get(f"{W}val", "1").isdigit() else 1
                vm = pr.find(f"{W}vMerge") if pr is not None else None
                col = len(row)
                if vm is not None and vm.get(f"{W}val") != "restart":     # продолжение объединения по вертикали
                    text = rows[-1][col] if rows and col < len(rows[-1]) else ""
                else:
                    text = self._cell(tc)
                row += [text] + [""] * (span - 1)
            if any(c.strip() for c in row):
                rows.append(row)
            if len(rows) >= MAX_TABLE_ROWS:
                break
        width = max((len(r) for r in rows), default=0)
        return [r + [""] * (width - len(r)) for r in rows]

    def _cell(self, tc) -> str:
        parts = []
        for el in tc:
            if el.tag == f"{W}p":
                out, boxes, pics = [], [], []
                _runs(el, out, boxes, pics)
                for rid in pics:
                    part = self.rels.get(rid, ("", ""))[0]
                    if part and part not in self.pictures:
                        self.pictures.append(part)
                s = "".join(out).strip()
                if s:
                    parts.append(s)
            elif el.tag == f"{W}tbl":                         # вложенная таблица — строками через «;»
                parts += ["; ".join(c for c in r if c) for r in self.table(el)]
            elif el.tag == f"{W}sdt":
                c = el.find(f"{W}sdtContent")
                if c is not None:
                    parts.append(self._cell(c))
        return " / ".join(p for p in parts if p)


def _direct(el, tag):
    """Строки таблицы или ячейки строки — свои, не из вложенной таблицы; обёртки sdt и customXml прозрачны."""
    for ch in el:
        if ch.tag == tag:
            yield ch
        elif ch.tag in (f"{W}sdt", f"{W}sdtContent", f"{W}customXml"):
            yield from _direct(ch, tag)


def _choice(alt):
    """mc:AlternateContent: одна из версий (иначе надпись или рисунок попадут дважды — из Choice и Fallback)."""
    ch = alt.find(f"{MC}Choice")
    return ch if ch is not None else (alt.find(f"{MC}Fallback") if alt.find(f"{MC}Fallback") is not None else [])


def _runs(el, out, boxes, pics):
    for ch in el:
        t = ch.tag
        if t in (f"{W}pPr", f"{W}rPr", f"{W}delText", f"{W}instrText", f"{W}del"):
            continue
        if t == f"{W}t" or t == f"{M}t":
            out.append(ch.text or "")
        elif t == f"{W}tab":
            out.append("\t")
        elif t in (f"{W}br", f"{W}cr"):
            out.append("\n")
        elif t == f"{W}noBreakHyphen":
            out.append("-")
        elif t == f"{W}sym":
            code = ch.get(f"{W}char", "")
            try:
                out.append(SYMBOL_CHARS.get(int(code, 16) & 0xFF, ""))
            except ValueError:
                pass
        elif t == f"{W}txbxContent":
            boxes.append(ch)
        elif t == f"{A}blip":
            rid = ch.get(f"{R}embed") or ch.get(f"{R}link")
            if rid:
                pics.append(rid)
        elif t == f"{V}imagedata":
            rid = ch.get(f"{R}id")
            if rid:
                pics.append(rid)
        elif t == f"{MC}AlternateContent":
            _runs(_choice(ch), out, boxes, pics)
        else:
            _runs(ch, out, boxes, pics)


# ---------------------------------------------------------------- запись простого .docx
def write_docx(blocks: list[tuple]) -> bytes:
    """Минимальный документ Word: ("h1"|"h2"|"p", текст), ("table", строки), ("image", байты PNG/JPEG).
    Для самопроверки сборки (без python-docx) и образцов в тестах."""
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))  # noqa: E731
    body, media, rels = [], [], ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>']

    def para(text, style=None):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'

    for kind, val in blocks:
        if kind in ("h1", "h2"):
            body.append(para(val, "Heading" + kind[1]))
        elif kind == "p":
            body.append(para(val))
        elif kind == "table":
            rows = "".join("<w:tr>" + "".join(f"<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>{para(c)}</w:tc>" for c in r) + "</w:tr>"
                           for r in val)
            grid = "".join('<w:gridCol w:w="2400"/>' for _ in val[0])
            body.append(f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
                        f'<w:tblGrid>{grid}</w:tblGrid>{rows}</w:tbl>')
        elif kind == "image":
            from PIL import Image

            k = len(media) + 1
            im = Image.open(io.BytesIO(val))
            ext = "jpeg" if im.format == "JPEG" else "png"
            media.append((f"word/media/image{k}.{ext}", val))
            rels.append(f'<Relationship Id="rIdImg{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                        f'Target="media/image{k}.{ext}"/>')
            cx = 5400000                                            # 15 см по ширине, высота — по пропорциям
            cy = int(cx * im.size[1] / im.size[0])
            body.append(
                f'<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                f'<wp:docPr id="{k}" name="Рисунок {k}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{k}" name="image{k}.{ext}"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="rIdImg{k}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    styles = (head + '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              + "".join(f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>'
                        f'<w:pPr><w:outlineLvl w:val="{n - 1}"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>' for n in (1, 2))
              + '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style></w:styles>')
    files = {
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>',
        "word/document.xml": head + f'<w:document {ns}><w:body>{"".join(body)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>',
        "word/styles.xml": styles,
        "word/_rels/document.xml.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels) + "</Relationships>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for part, text in files.items():
            z.writestr(part, text.encode("utf-8"))
        for part, blob in media:
            z.writestr(part, blob)
    return buf.getvalue()
