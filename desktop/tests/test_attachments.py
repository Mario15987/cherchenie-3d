"""Вложения ИИ-помощника: фото чертежей и деталей, Word (.docx), текст.

1. Word: текст, заголовки, таблица размеров, вложенная картинка — и в файле от python-docx (как из Word), и в простом
   .docx из write_docx (им пользуется самопроверка сборки).
2. Фото: поворот по EXIF, сжатие до 1600 px, JPEG в Base64; локальный анализ находит пропорции, отверстия и массив.
3. Vision-запрос: блоки image (Anthropic), image_url (OpenAI, OpenRouter, Groq), inlineData (Gemini); ответные
   JSON-команды строят деталь на холсте. Сеть не нужна: сервер подменён.
4. Интерфейс: «📎 Прикрепить», перетаскивание в чат, Ctrl+V со скриншотом, лента с «×», три быстрых сценария.

Запуск: .venv/Scripts/python -m unittest tests.test_attachments
"""
from __future__ import annotations

import base64
import io
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from tests.env import APP, ERRORS, TMP  # noqa: F401  — окна без показа, временные config.json и user_library.json
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from cad import ai, attachments as at, params, samples, vision  # noqa: E402
from cad.dialogs import Ask  # noqa: E402
from cad.mainwindow import MainWindow  # noqa: E402

try:
    import docx as python_docx  # только для тестов: файл «как из Word»
except ImportError:  # pragma: no cover
    python_docx = None

PLATE_ACTIONS = [{"op": "add_rect", "x": 0, "y": 0, "w": 120, "h": 80},
                 {"op": "add_circle", "cx": 60, "cy": 40, "d": 30, "axes": True},
                 *[{"op": "add_circle", "cx": 60 + 30 * c, "cy": 40 + 30 * s, "d": 8}
                   for c, s in ((0.7071, 0.7071), (-0.7071, 0.7071), (-0.7071, -0.7071), (0.7071, -0.7071))],
                 {"op": "add_dim", "x1": 0, "y1": 0, "x2": 120, "y2": 0, "off": -10, "kind": "horizontal"},
                 {"op": "add_dim", "x1": 0, "y1": 0, "x2": 0, "y2": 80, "off": -10, "kind": "vertical"},
                 {"op": "add_diadim", "cx": 60, "cy": 40, "r": 15, "ang": 45}]


@contextmanager
def fake_servers(reply: dict):
    """Подмена всех провайдеров: запросы записываются, ответ — reply. Без сети."""
    import anthropic

    sent = {}
    text = json.dumps(reply, ensure_ascii=False)

    class FakeClaude:
        def __init__(self, **kw):
            self.messages = self.beta = self

        def create(self, **kw):
            sent["anthropic"] = kw
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])

    def fake_post(url, body, headers, timeout=0):
        key = "gemini" if ":generateContent" in url else "openai"
        sent[key] = body
        sent[key + "_url"] = url
        if key == "gemini":
            return {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        return {"choices": [{"message": {"content": text}}]}
    real_post, real_client = ai._post_json, anthropic.Anthropic
    ai._post_json, anthropic.Anthropic = fake_post, FakeClaude
    try:
        yield sent
    finally:
        ai._post_json, anthropic.Anthropic = real_post, real_client


def png(w=600, h=400, color="white") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class AttachmentCoreTest(unittest.TestCase):
    # ------------------------------------------------------------ 1. Word
    @unittest.skipIf(python_docx is None, "нет python-docx")
    def test_docx_from_python_docx(self):
        """Документ, собранный python-docx так же, как его пишет Word: заголовки, список, таблица с объединением, рисунок."""
        d = python_docx.Document()
        d.add_heading("ТЗ на кронштейн", level=1)
        d.add_paragraph("Материал — сталь 09Г2С, толщина листа 6 мм.")
        d.add_paragraph("Отверстия сквозные", style="List Bullet")
        d.add_heading("Размеры", level=2)
        t = d.add_table(rows=4, cols=3)
        rows = [["Параметр", "Обозн.", "Значение, мм"], ["Длина", "L", "150"], ["Ширина", "B", "60"], ["Отверстие", "Ø", "12"]]
        for r, vals in enumerate(rows):
            for c, v in enumerate(vals):
                t.cell(r, c).text = v
        merged = d.add_table(rows=2, cols=2)
        merged.cell(0, 0).merge(merged.cell(0, 1)).text = "Шапка"
        merged.cell(1, 0).text, merged.cell(1, 1).text = "a", "b"
        d.add_picture(io.BytesIO(samples.plate_image(900, 600)))
        d.add_paragraph("Конец.")
        buf = io.BytesIO()
        d.save(buf)
        doc = at.parse_docx(buf.getvalue(), "кронштейн.docx")
        self.assertIn("# ТЗ на кронштейн", doc.markdown)
        self.assertIn("## Размеры", doc.markdown)
        self.assertIn("- Отверстия сквозные", doc.markdown)
        self.assertEqual(doc.tables[0], rows)
        self.assertIn("| Длина | L | 150 |", doc.markdown)
        self.assertEqual(doc.tables[1][0], ["Шапка", ""], "объединённые по горизонтали ячейки")
        self.assertEqual(len(doc.images), 1)
        self.assertIn("[рисунок 1]", doc.markdown)
        self.assertLess(doc.markdown.index("[рисунок 1]"), doc.markdown.index("Конец."), "рисунок — на своём месте в тексте")
        atts = at.docx_attachments(buf.getvalue(), "кронштейн.docx")
        self.assertEqual([a.kind for a in atts], ["docx", "image"])
        self.assertEqual(atts[1].parent, "кронштейн.docx")
        self.assertEqual(atts[0].info["tables"], 2)

    def test_docx_saved_by_word(self):
        """Файл, сохранённый Microsoft Word: стили «Заголовок 1/2», Ø шрифтом Symbol, маркированный список, таблица
        с объединённой строкой, рисунок, надпись (Word пишет её дважды — в mc:Choice и mc:Fallback)."""
        atts = at.load(Path(__file__).parent / "fixtures" / "word_spec.docx")
        doc = atts[0]
        self.assertIn("# Техническое задание на фланец", doc.text)
        self.assertIn("## Размеры", doc.text)
        self.assertIn("центральное отверстие Ø40 мм", doc.text)
        self.assertIn("- Отверстия крепления сквозные", doc.text)
        self.assertEqual(doc.tables[0][1], ["Наружный диаметр", "D", "140"])
        self.assertEqual(doc.tables[0][4], ["Примечание: 4 отверстия Ø14", "", ""])
        self.assertEqual(doc.text.count("неуказанные фаски 1×45°"), 1, "надпись — один раз")
        self.assertEqual([a.kind for a in atts], ["docx", "image"])
        self.assertEqual(atts[1].size, (900, 600))

    def test_docx_builtin_writer_and_parser(self):
        raw = samples.spec_docx()
        atts = at.docx_attachments(raw, "ТЗ.docx")
        doc = atts[0]
        self.assertEqual(doc.kind, "docx")
        self.assertIn("# Техническое задание на пластину опорную", doc.text)
        self.assertIn("Ст3", doc.text)
        self.assertEqual(doc.tables, [samples.SPEC_ROWS])
        self.assertIn("| Длина, мм | 120 |", doc.text)
        self.assertEqual(doc.info["images"], 1)
        self.assertEqual(atts[1].kind, "image")
        self.assertEqual(atts[1].size, (800, 600))
        self.assertIn("Документ Word «ТЗ.docx»", doc.prompt_text())
        if python_docx is not None:          # тот же файл читается python-docx — это настоящий .docx
            d = python_docx.Document(io.BytesIO(raw))
            self.assertEqual(d.paragraphs[0].text, "Техническое задание на пластину опорную")
            self.assertEqual(d.tables[0].cell(1, 1).text, "120")
            self.assertEqual(len(d.inline_shapes), 1)

    def test_docx_tricky_markup(self):
        """Символ Ø шрифтом Symbol, разрыв строки, надпись (text box), вложенная таблица, удалённая правка."""
        body = ('<w:p><w:r><w:t>Отверстие </w:t></w:r><w:r><w:sym w:font="Symbol" w:char="F0C6"/><w:t>20</w:t></w:r>'
                '<w:del><w:r><w:delText>старое</w:delText></w:r></w:del><w:r><w:br/><w:t>вторая строка</w:t></w:r>'
                '<w:r><w:pict><v:shape><v:textbox><w:txbxContent><w:p><w:r><w:t>В надписи</w:t></w:r></w:p></w:txbxContent>'
                '</v:textbox></v:shape></w:pict></w:r></w:p>'
                '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>внешняя</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>вн1</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:p><w:r><w:t>вн2</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:tc><w:tc><w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc></w:tr>'
                '<w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc><w:tc><w:p><w:r><w:t>y</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        raw = io.BytesIO()
        import zipfile

        with zipfile.ZipFile(raw, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                       'xmlns:v="urn:schemas-microsoft-com:vml"><w:body>' + body + "</w:body></w:document>")
        doc = at.parse_docx(raw.getvalue())
        self.assertIn("Отверстие Ø20\nвторая строка", doc.markdown)
        self.assertNotIn("старое", doc.markdown)
        self.assertIn("В надписи", doc.markdown)
        self.assertEqual(doc.tables[0], [["внешняя / вн1; вн2", "x"], ["внешняя / вн1; вн2", "y"]], "вложенная таблица и vMerge")

    def test_bad_files(self):
        with self.assertRaisesRegex(at.AttachError, "не zip"):
            at.parse_docx(b"PK? not really", "x.docx")
        old = TMP / "старый.doc"
        old.write_bytes(b"\xd0\xcf\x11\xe0")
        with self.assertRaisesRegex(at.AttachError, r"\.docx"):
            at.load(old)
        with self.assertRaisesRegex(at.AttachError, "не прикрепляются"):
            at.load(TMP / "x.pdf")
        broken = TMP / "битое.png"
        broken.write_bytes(b"\x89PNG not an image")
        with self.assertRaisesRegex(at.AttachError, "изображение"):
            at.load(broken)

    # ------------------------------------------------------------ 2. фото и анализ
    def test_image_exif_resize_base64(self):
        from PIL import Image

        im = Image.new("RGB", (4000, 3000), "white")
        exif = Image.Exif()
        exif[0x0112] = 6                                  # телефон держали вертикально
        buf = io.BytesIO()
        im.save(buf, "JPEG", exif=exif)
        a = at.image(buf.getvalue(), "IMG_0001.jpg", analyze=False)
        self.assertEqual(a.source_size, (4000, 3000))
        self.assertEqual(a.size, (1200, 1600), "повёрнуто по EXIF и сжато до 1600 по длинной стороне")
        self.assertEqual(a.media_type, "image/jpeg")
        self.assertTrue(base64.b64decode(a.b64).startswith(b"\xff\xd8"))
        self.assertTrue(a.data_url().startswith("data:image/jpeg;base64,/9j/"))
        self.assertTrue(a.thumb.startswith(b"\x89PNG"))
        rgba = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
        buf = io.BytesIO()
        rgba.save(buf, "PNG")
        flat = Image.open(io.BytesIO(at.image(buf.getvalue(), "t.png", analyze=False).data))
        self.assertGreater(min(flat.getpixel((5, 5))), 245, "прозрачное — на белом, а не чёрном")
        for fmt in ("WEBP", "BMP"):
            buf = io.BytesIO()
            im.resize((800, 600)).save(buf, fmt)
            self.assertEqual(at.image(buf.getvalue(), f"x.{fmt.lower()}", analyze=False).size, (800, 600))

    def test_vision_drawing_and_photo(self):
        from PIL import Image

        for photo in (False, True):
            res = vision.analyze(Image.open(io.BytesIO(samples.plate_image(2400, 1800, "JPEG" if photo else "PNG", photo=photo))))
            circles = res["окружности"]
            big = max(circles, key=lambda c: c["d"])
            self.assertAlmostEqual(big["d"], 30 / 120, delta=0.02, msg="Ø30 на ширине 120")
            self.assertAlmostEqual(big["x"], 0.5, delta=0.02)
            small = [c for c in circles if abs(c["d"] - 8 / 120) < 0.015]
            self.assertEqual(len(small), 4, circles)
            pattern = next(p for p in res["массивы_отверстий"] if p["число"] == 4)
            self.assertAlmostEqual(pattern["d_центров"], 60 / 120, delta=0.03)
            self.assertTrue(pattern["соосно"])
            self.assertAlmostEqual(pattern["угол_первой"], 45, delta=3)
            self.assertGreaterEqual(res["прямые"]["горизонтальных"], 2)
            self.assertGreaterEqual(res["прямые"]["вертикальных"], 2)
            if photo:
                self.assertEqual(res["тип"], "предмет на фоне (фото детали)")
                self.assertAlmostEqual(res["пропорции_ш_к_в"], 1.5, delta=0.05)
                self.assertGreater(res["симметрия"]["вертикальная_ось"], 0.9)
            else:
                self.assertIn("чертёж", res["тип"])
            text = vision.summary(res)
            self.assertIn("4 одинаковых окружностей", text)
            self.assertIn("пропорции", text)

    def test_vision_paper_on_table(self):
        """Лист с чертежом, сфотографированный на тёмном столе: разбирается то, что на листе."""
        from PIL import Image

        sheet = Image.open(io.BytesIO(samples.plate_image(1600, 1200)))
        photo = Image.new("RGB", (2200, 1700), (35, 30, 28))
        photo.paste(sheet, (300, 250))
        res = vision.analyze(photo)
        self.assertIn("лист_на_фото", res)
        self.assertEqual(len([c for c in res["окружности"] if abs(c["d"] - 8 / 120) < 0.015]), 4)

    def test_text_files(self):
        csv_raw = "Опора;Тип;Пролёт, м\nОП-1;П10-3;35\nОП-2;П10-3;40\n".encode("cp1251")
        a = at.text_file(csv_raw, "ведомость.csv")
        self.assertEqual(a.tables[0][1], ["ОП-1", "П10-3", "35"])
        self.assertIn("| ОП-2 | П10-3 | 40 |", a.text)
        j = at.text_file(json.dumps({"L": 120, "материал": "Ст3"}, ensure_ascii=False).encode("utf-8"), "p.json")
        self.assertIn('"материал": "Ст3"', j.text)
        t = at.text_file("Длина 120 мм".encode("utf-16"), "тз.txt")
        self.assertEqual(t.text, "Длина 120 мм")
        self.assertIn("Файл «тз.txt»", t.prompt_text())

    # ------------------------------------------------------------ 3. форматы Vision API
    def test_provider_formats(self):
        pic = at.image(samples.plate_image(1200, 900), "plate.png")
        doc = at.docx_attachments(samples.spec_docx(), "ТЗ.docx")
        content = ai.user_content("начерти", [pic, *doc])
        self.assertIsInstance(content, list)
        self.assertEqual(content[-1], {"type": "text", "text": "Запрос пользователя: начерти"})
        self.assertIn("| Длина, мм | 120 |", content[0]["text"], "документ — текстом с таблицей")
        self.assertIn("Локальный анализ изображения", content[1]["text"], "сводка анализа перед картинкой")
        msgs = [{"role": "user", "content": content}]
        a = ai.provider_messages("anthropic", msgs)[0]["content"]
        img = next(b for b in a if b["type"] == "image")
        self.assertEqual(img["source"], {"type": "base64", "media_type": "image/jpeg", "data": pic.b64})
        o = ai.provider_messages("openai", msgs)[0]["content"]
        url = next(b for b in o if b["type"] == "image_url")["image_url"]
        self.assertEqual(url, {"url": "data:image/jpeg;base64," + pic.b64, "detail": "high"})
        for prov in ("openrouter", "groq", "custom"):
            u = next(b for b in ai.provider_messages(prov, msgs)[0]["content"] if b["type"] == "image_url")["image_url"]
            self.assertEqual(u, {"url": "data:image/jpeg;base64," + pic.b64})
        g = ai.provider_messages("gemini", msgs)[0]
        self.assertEqual(g["role"], "user")
        self.assertIn({"inlineData": {"mimeType": "image/jpeg", "data": pic.b64}}, g["parts"])
        self.assertEqual(ai.user_content("только текст", [doc[0]])[:15], "Документ Word «", "без картинок — строка")
        # не больше 3 картинок для Groq, переписка не тащит старые фото
        many = ai.user_content("x", [pic] * 7)
        groq = ai.provider_messages("groq", [{"role": "user", "content": many}], ai.image_limit({"provider": "groq"}))[0]["content"]
        self.assertEqual(sum(1 for b in groq if b["type"] == "image_url"), 3)
        hist = ai.compact_history([{"role": "user", "content": content}, {"role": "assistant", "content": "{}"},
                                   {"role": "user", "content": ai.user_content("ещё", [pic])}])
        self.assertFalse(ai.has_images(hist[0]["content"]), "старое фото — пометкой")
        self.assertTrue(ai.has_images(hist[2]["content"]))
        self.assertIn("Сценарий Б", ai.ATTACH_TEXT)

    def test_ask_every_provider_offline(self):
        pic = at.image(samples.plate_image(1200, 900, "JPEG"), "plate.jpg")
        msgs = [{"role": "user", "content": ai.user_content("начерти", [pic])}]
        with fake_servers({"message": "ок", "actions": PLATE_ACTIONS}) as sent:
            for prov, model in (("anthropic", "claude-opus-5-5"), ("openai", "gpt-x"), ("openrouter", "a/b"), ("groq", "llama-vision"),
                                ("gemini", "gemini-x")):
                reply = ai.ask({"provider": prov, "api_key": "k", "model": model, "base_url": ""}, "system", msgs)
                self.assertEqual(len(reply["actions"]), len(PLATE_ACTIONS), prov)
            self.assertEqual(sent["anthropic"]["messages"][0]["content"][1]["type"], "image")
            self.assertEqual(sent["openai_url"], "https://api.groq.com/openai/v1/chat/completions", "последний — Groq")
            self.assertTrue(sent["openai"]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
            self.assertIn("inlineData", sent["gemini"]["contents"][0]["parts"][1])


class AttachmentUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Ask.AUTO = True
        cls.w = MainWindow()
        cls.w.resize(1400, 900)
        cls.w.show()
        APP.processEvents()
        cls.img = TMP / "фланец.jpg"
        cls.img.write_bytes(samples.plate_image(3200, 2400, "JPEG"))
        cls.doc = TMP / "ТЗ_пластина.docx"
        cls.doc.write_bytes(samples.spec_docx())

    @classmethod
    def tearDownClass(cls):
        cls.w.dirty = False
        cls.w.close()
        Ask.AUTO = False

    def setUp(self):
        ERRORS.clear()
        Ask.answers = {}
        w = self.w
        w.cfg["canvas"] = "fragment"
        w.new_project()
        w.work.setCurrentIndex(0)
        w.attachments = []
        w.attach_bar.set_items([])
        w.chat_input.clear()
        w.show_ai()

    def tearDown(self):
        self.assertEqual(ERRORS, [], "исключения в обработчиках Qt")

    def send_and_wait(self):
        w = self.w
        w.wait_attachments()
        if w.worker is not None:
            w.worker.wait(20000)
        APP.processEvents()
        APP.processEvents()

    def test_attach_button_chips_and_remove(self):
        w = self.w
        self.assertEqual(w.ai_attach_btn.text(), "📎 Прикрепить")
        self.assertTrue(w.ai_panel.isAncestorOf(w.ai_attach_btn))
        Ask.answers = {"attach.paths": [str(self.img), str(self.doc)]}
        w.ai_attach_btn.click()
        w.wait_attachments()
        self.assertEqual([a.kind for a in w.attachments], ["image", "docx", "image"])
        self.assertTrue(w.attach_bar.isVisible())
        self.assertEqual(len(w.attach_bar.chips), 3)
        self.assertEqual(w.attachments[0].size, (1600, 1200))
        self.assertFalse(w.attach_bar.chips[0].findChild(type(w.ai_status)).pixmap().isNull(), "миниатюра фото")
        w.attach_bar.chips[1].close_btn.click()         # «×» у документа убирает и его рисунок
        APP.processEvents()
        self.assertEqual([a.name for a in w.attachments], ["фланец.jpg"])
        w.attach_bar.chips[0].close_btn.click()
        APP.processEvents()
        self.assertEqual(w.attachments, [])
        self.assertFalse(w.attach_bar.isVisible())

    def test_drag_drop_and_ctrl_v(self):
        w = self.w
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(self.img))])
        for target in (w.chat_view.viewport(), w.ai_panel, w.chat_input.viewport()):
            enter = QDragEnterEvent(QPointF(20, 20), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
            APP.sendEvent(target, enter)
            self.assertTrue(enter.isAccepted(), target)
            self.assertTrue(w.ai_panel.property("dropping"), "подсветка при перетаскивании")
            APP.sendEvent(target, QDropEvent(QPointF(20, 20), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
            self.assertFalse(w.ai_panel.property("dropping"))
        w.wait_attachments()
        self.assertEqual([a.name for a in w.attachments], ["фланец.jpg"] * 3)
        # скриншот в буфере → Ctrl+V в поле запроса
        shot = QImage(640, 480, QImage.Format_RGB32)
        shot.fill(Qt.white)
        APP.clipboard().setImage(shot)
        w.chat_input.setFocus()
        QTest.keySequence(w.chat_input, QKeySequence.Paste)
        w.wait_attachments()
        self.assertTrue(w.attachments[-1].name.startswith("Скриншот"), [a.name for a in w.attachments])
        self.assertEqual(w.attachments[-1].size, (640, 480))
        self.assertEqual(w.chat_input.toPlainText(), "", "картинка не вставилась текстом")
        # картинка из браузера: вместе с ней в буфере только её адрес — прикрепляется картинкой
        md = QMimeData()
        md.setImageData(shot)
        md.setText("https://example.com/flange.png")
        n = len(w.attachments)
        w.chat_input.insertFromMimeData(md)
        w.wait_attachments()
        self.assertEqual(len(w.attachments), n + 1)
        # обычный текст по-прежнему вставляется текстом
        APP.clipboard().setText("Ø40 H7")
        QTest.keySequence(w.chat_input, QKeySequence.Paste)
        self.assertEqual(w.chat_input.toPlainText(), "Ø40 H7")
        n = len(w.attachments)
        w.attach_files([str(TMP / "чертёж.pdf")])          # неподдерживаемое — сообщение, вложение не появляется
        w.wait_attachments()
        self.assertEqual(len(w.attachments), n)
        self.assertIn("не прикрепляются", w.chat_view.toPlainText())

    def test_presets_exist(self):
        labels = [self.w.ai_preset_btns[k].text() for k, *_ in ai.ATTACH_PRESETS]
        self.assertEqual(labels, ["Оцифровать фото чертежа / эскиза", "Начертить деталь по фото", "Построить чертеж / схему по ТЗ из Word"])
        for b in self.w.ai_preset_btns.values():
            self.assertTrue(self.w.ai_panel.isAncestorOf(b))

    def test_scenario_b_photo_of_part_to_3d(self):
        """«Начертить деталь по фото»: запрос с фото в Base64 (Anthropic), ответ — эскиз с размерами и выдавливание."""
        w = self.w
        w.cfg.update(provider="anthropic", api_key="test", model="claude-opus-5-5")
        w.attach_files([str(self.img)])
        w.wait_attachments()
        w.chat_input.setPlainText("толщина 10 мм")
        with fake_servers({"message": "Пластина 120×80×10", "actions": PLATE_ACTIONS + [{"op": "extrude", "height": 10}]}) as sent:
            w.ai_preset_btns["photo_part"].click()
            self.send_and_wait()
        user = sent["anthropic"]["messages"][-1]["content"]
        self.assertEqual(user[1]["type"], "image")
        self.assertEqual(user[1]["source"]["media_type"], "image/jpeg")
        self.assertIn("Сценарий Б", user[-1]["text"])
        self.assertIn("толщина 10 мм", user[-1]["text"])
        self.assertIn("Сценарий Б", sent["anthropic"]["system"])
        lo, hi = w.solid.bbox()
        self.assertEqual([round(float(v), 3) for v in hi - lo], [120, 80, 10])
        dims = [e for e in w.project.drawing if e["type"] in ("dim", "diadim")]
        self.assertEqual(len(dims), 3)
        self.assertTrue(all(params.associative(d) for d in dims), "размеры управляющие")
        self.assertEqual(w.attachments, [], "вложения ушли с сообщением")
        self.assertIn("Начертить деталь по фото", w.chat_view.toPlainText())

    def test_scenario_a_photo_of_drawing_on_sheet(self):
        """«Оцифровать фото чертежа»: на листе А4, OpenAI image_url; размеры ассоциативны — правка Ø меняет окружность."""
        w = self.w
        w.set_canvas("A4P")
        w.work.setCurrentIndex(1)
        w.cfg.update(provider="openai", api_key="test", model="gpt-test")
        w.attach_files([str(self.img)])
        w.wait_attachments()
        fx, fy = w.project.frame["x"] + 40, w.project.frame["y"] + 120
        acts = [{**a, **{k: a[k] + (fx if k in ("x", "cx", "x1", "x2") else fy) for k in ("x", "y", "cx", "cy", "x1", "y1", "x2", "y2") if k in a}}
                for a in PLATE_ACTIONS]
        with fake_servers({"message": "Чертёж пластины", "actions": acts}) as sent:
            w.ai_preset_btns["photo_drawing"].click()
            self.send_and_wait()
        parts = sent["openai"]["messages"][-1]["content"]
        self.assertTrue(any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/jpeg;base64,") for p in parts))
        self.assertTrue(any("4 одинаковых окружностей" in p.get("text", "") for p in parts), "сводка анализа в запросе")
        self.assertEqual(w.work.currentIndex(), 1)
        hole = next(e for e in w.project.drawing if e["type"] == "circle" and abs(e["r"] - 15) < 1e-6)
        dia = next(e for e in w.project.drawing if e["type"] == "diadim")
        w.history.push()
        params.drive_dim(w.project, dia, 40)
        self.assertAlmostEqual(hole["r"], 20, msg="Ø30 → Ø40 размером")
        self.assertNotIn("✗", w.chat_view.toPlainText())

    def test_scenario_c_word_spec_opens_dialog_and_sends(self):
        """«Построить чертеж по ТЗ из Word» без вложения: выбор файла, разбор, запрос уходит сам (Gemini inlineData)."""
        w = self.w
        w.cfg.update(provider="gemini", api_key="test", model="gemini-test")
        Ask.answers = {"attach.paths": [str(self.doc)]}
        reply = {"message": "Лист А4 по ТЗ", "actions": [{"op": "set_canvas", "mode": "A4P"}] + PLATE_ACTIONS}
        with fake_servers(reply) as sent:
            w.ai_preset_btns["word_spec"].click()
            self.send_and_wait()
        parts = sent["gemini"]["contents"][-1]["parts"]
        texts = "\n".join(p.get("text", "") for p in parts)
        self.assertIn("| Длина, мм | 120 |", texts, "таблица Word в запросе")
        self.assertIn("Сценарий В", texts)
        self.assertTrue(any("inlineData" in p for p in parts), "рисунок из документа — картинкой")
        self.assertEqual(w.project.canvas_mode(), "A4P")
        self.assertEqual(w.work.currentIndex(), 1, "лист открыт")

    def test_failed_request_keeps_attachments(self):
        w = self.w
        w.cfg.update(provider="openai", api_key="", model="gpt-test")
        w.attach_files([str(self.img)])
        w.wait_attachments()
        w.chat_input.setPlainText("начерти")
        w.ai_send_btn.click()
        self.send_and_wait()
        self.assertIn("API-ключ", w.chat_view.toPlainText())
        self.assertEqual([a.name for a in w.attachments], ["фланец.jpg"], "вложение вернулось для повторной отправки")
        self.assertTrue(w.attach_bar.isVisible())


if __name__ == "__main__":
    unittest.main()
